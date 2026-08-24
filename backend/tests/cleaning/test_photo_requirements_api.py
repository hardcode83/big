"""R1-R5 — `GET /api/v1/cleaning-tasks/{id}/photo-requirements`, end to end over ASGI.

What only this level can show, and why task 2.4 insists on it:

* **The field set is closed on the SERIALISED body.** A schema that enumerates four fields is an
  intention; a body whose keys are exactly those four is the guarantee (R4.5). The template row
  the projection reads carries `id`, `name`, `property_id`, `active` and the raw `items`, so the
  fixture below gives every one of them a recognisable value and the assertions search the real
  bytes that would be there if the guarantee broke.
* **R2.3 is a contract requirement, not a behaviour.** Nothing in the running system reads the
  route's `description`, so a refactor could drop it and the whole suite would stay green. It is
  asserted here against the generated document, both directions, because what `cleaner-app` will
  read is the published operation.
* **The RBAC gate is the wiring's, not the use case's.** `require(READ_CLEANING_TASKS)` is a
  dependency; only a real request proves it is the one declared.

The per-branch rules are pinned in `test_photo_requirements_use_case.py` against fakes; here
they are checked to survive the wiring.

**On the tenant-isolation cases.** The cross-tenant `404` asserted over HTTP is about the shape
of the answer and is deliberately **not** the proof that the isolation works: the `api` fixture
hands every request the same session and an authenticated request marks it with the caller's
tenant, so the loader criteria of `app/core/db.py` would filter a cross-tenant read even with
the explicit filter deleted. That proof is
`test_the_tenant_filter_is_load_bearing_on_an_unmarked_session` at the bottom of this file,
which drives the use case with the **real** repositories over the unbound `db_session` — the
same arrangement, and for the same reason, as `test_task_incident_use_case.py`. It matters more
here than usual: `cleaning_photos` has no `tenant_id` column of its own, so the `JOIN` inside
`uploaded_photo_types` is the entire mechanism and no global listener backs it up.
"""

import uuid

import pytest
import pytest_asyncio

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.cleaning.application.use_cases import (
    CleaningActor,
    GetPhotoRequirementsUseCase,
)
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import (
    TASK_NOT_FOUND_MESSAGE,
    CleaningTaskNotFoundError,
)
from app.cleaning.infrastructure.models import CleaningPhotoModel
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningPhotoRepository,
    SqlAlchemyCleaningTaskRepository,
)
from app.core.openapi import build_openapi
from app.main import create_app
from tests.cleaning.conftest import auth_header, insert_task, insert_template

TASKS = "/api/v1/cleaning-tasks"

#: The four keys of `PhotoRequirementStateResponse`, written out rather than derived from the
#: model: a set computed from `model_fields` would agree with any mistake in it, and this is the
#: contract a client is written against (R4.5, the `CONTEXT_FIELDS` pattern of
#: `tests/maintenance/test_incident_context_api.py`).
PHOTO_REQUIREMENT_FIELDS = {"photo_type", "label", "required", "uploaded"}

#: Every header this route answers with, written by hand for the same reason
#: `PHOTO_REQUIREMENT_FIELDS` is: a set computed from the response would agree with any header
#: added to it. `x-content-type-options` is `NoSniffMiddleware`'s, the other two are the server's;
#: none of the three is this capability's. A verdict travels in a header as well as in a field
#: (R3.2), and the diff against `/checklist` cannot see one that was added to both — which is
#: what anything mounted above the route does.
BASELINE_RESPONSE_HEADERS = {"content-length", "content-type", "x-content-type-options"}

#: Deliberately not alphabetical and deliberately mixed on `required`: alphabetical order would
#: let a `sorted()` implementation pass R1.3, and an all-required list could not tell
#: `required_photos` from `required_photo_types()` (R2.2).
PHOTOS = [
    {"photo_type": "kitchen", "label": "Cocina", "required": True},
    {"photo_type": "before", "label": "Antes de empezar", "required": False},
    {"photo_type": "aftermath", "label": "Al terminar", "required": True},
]

#: Values that would be unmistakable in the body if any of them leaked (R4.4).
TEMPLATE_NAME = "PLANTILLA-QUE-NO-DEBE-SALIR"
TEMPLATE_ITEMS = [{"item_id": "itemquenodebesalir", "label": "ITEM-QUE-NO-DEBE-SALIR"}]


async def _insert_cleaner(session, tenant) -> UserModel:
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Limpiadora",
        email=f"cleaner-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x" * 60,
        role=UserRole.CLEANER,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def cleaner_a(db_session, tenant_a):
    return await _insert_cleaner(db_session, tenant_a)


@pytest_asyncio.fixture
async def other_cleaner_a(db_session, tenant_a):
    """A second cleaner **of the same tenant** — the R1.5 case tenant scoping alone misses."""
    return await _insert_cleaner(db_session, tenant_a)


@pytest_asyncio.fixture
async def cleaner_b(db_session, tenant_b):
    return await _insert_cleaner(db_session, tenant_b)


@pytest_asyncio.fixture
async def photo_template_a(db_session, tenant_a, property_a):
    """Three photo types, and every other template field set to something recognisable."""
    return await insert_template(
        db_session,
        tenant_a,
        property_id=property_a.id,
        name=TEMPLATE_NAME,
        items=TEMPLATE_ITEMS,
        required_photos=PHOTOS,
    )


@pytest_asyncio.fixture
async def task_a(db_session, tenant_a, property_a, photo_template_a, cleaner_a):
    return await insert_task(
        db_session,
        tenant_a,
        property_a,
        photo_template_a,
        status=CleaningTaskStatus.CREATED,
        cleaner=cleaner_a,
    )


@pytest_asyncio.fixture
async def task_b(db_session, tenant_b, property_b, template_b, cleaner_b):
    return await insert_task(db_session, tenant_b, property_b, template_b, cleaner=cleaner_b)


async def _add_photo(db_session, task, uploader, *, photo_type: str) -> CleaningPhotoModel:
    photo = CleaningPhotoModel(
        id=uuid.uuid4(),
        cleaning_task_id=task.id,
        uploaded_by=uploader.id,
        photo_type=photo_type,
        storage_key=f"tenants/{task.tenant_id}/cleaning-tasks/{task.id}/{uuid.uuid4()}.jpg",
    )
    db_session.add(photo)
    await db_session.flush()
    return photo


async def _get(api, task_id, user):
    return await api.get(
        f"{TASKS}/{task_id}/photo-requirements", headers=auth_header(api, user)
    )


# --- the happy path ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_assigned_cleaner_gets_one_entry_per_declared_type(
    api, task_a, cleaner_a
):
    """R1.1 — `photo_type` and `label`, one entry per declared type."""
    response = await _get(api, task_a.id, cleaner_a)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [(entry["photo_type"], entry["label"]) for entry in data] == [
        ("kitchen", "Cocina"),
        ("before", "Antes de empezar"),
        ("aftermath", "Al terminar"),
    ]


@pytest.mark.asyncio
async def test_every_entry_carries_exactly_the_four_fields(api, task_a, cleaner_a):
    """R4.5 — the closed field set, on the serialised body.

    Adding a field must be a deliberate act: this constant is written by hand, so a fifth key
    fails here and has to be added on purpose rather than drifting in behind a convenient
    `from_attributes`.
    """
    response = await _get(api, task_a.id, cleaner_a)

    data = response.json()["data"]
    assert data, "the fixture template declares three types; an empty body proves nothing"
    for entry in data:
        assert set(entry) == PHOTO_REQUIREMENT_FIELDS


@pytest.mark.asyncio
async def test_the_body_is_a_single_data_key(api, task_a, cleaner_a):
    """R2.1 — the collection is `data`, never `required_photos`.

    The column's name is the ambiguity this change refuses to inherit: belonging to the
    collection means *admissible*, and `required` alone means *demanded at the close*.
    """
    body = (await _get(api, task_a.id, cleaner_a)).json()

    assert set(body) == {"data"}
    assert "required_photos" not in body


@pytest.mark.asyncio
async def test_the_envelope_carries_no_verdict_key_of_its_own(api, task_a, cleaner_a):
    """R3.2 — at the TOP level, which is the half the per-entry check cannot see.

    `test_the_body_carries_no_verdict_field` above inspects the keys inside each `data` entry,
    and the structural guard inspects `PhotoRequirementView`'s fields. Neither looks at the
    envelope, so a `satisfied` computed on `PhotoRequirementsResponse` itself — a
    `@computed_field`, whose body is a single `return` and therefore passes every shape guard in
    `test_completion_clause_contract.py` — reaches the client and is caught only by
    `test_the_body_is_a_single_data_key`, whose subject is naming hygiene (R2.1). If that
    assertion is ever relaxed to admit a `meta` key, R3.2 would lose its only net for this shape.
    R3.2 gets its own here, stated as its own requirement.
    """
    body = (await _get(api, task_a.id, cleaner_a)).json()

    assert set(body) == {"data"}, (
        f"the envelope grew {sorted(set(body) - {'data'})}. Whether the task may be closed is "
        "answered by `CleaningTask.complete()` and by nothing else (R3.2, R3.3); this response "
        "reports what is filed."
    )


@pytest.mark.asyncio
async def test_the_route_adds_no_response_header_of_its_own(api, task_a, cleaner_a):
    """R3.2 — the other channel a client can read, closed behaviourally.

    Every structural guard on this capability asserts the *shape of some file*, and the review
    panel walked through three rounds of them the same way each time: by moving the derivation
    to a file the round's whitelist did not list. The body was already closed by key
    (`test_the_body_is_a_single_data_key`); a header was not closed by anything, and a completion
    verdict reaches the client through one exactly as well as through a field.

    So this asserts the channel instead of the source, and does not care which file would have
    computed the leak — a `Response` taken by the handler, by a provider in `dependencies.py` or
    by something listed in the route's `dependencies=` all fail here identically.

    **Two assertions, because neither alone is enough**, and the first version of this test had
    only the second:

    * the **closed set** catches a header added from *above* the route — the `APIRouter`,
      `include_router`, or app-wide middleware — which the comparison below cannot, because such
      a header lands on `/checklist` too and the difference comes out empty. That is a real
      escape and it was found by review, not imagined: the baseline is poisonable from above.
    * the **comparison with `/checklist`** catches a header added to this route alone without
      needing the constant to be right, and keeps the constant honest about what is shared: both
      are `ReadDep` `GET`s behind the same middleware stack.

    What neither covers is a verdict encoded in the *value* of a header both routes already
    carry. That is named as an accepted residual in `design.md` §Residuos; the structural guards
    on `use_cases.py`, `dependencies.py` and `schemas.py` are what make it unreachable from this
    capability's own code, and nothing in the app conditions a header value on this path today.
    """
    mine = await _get(api, task_a.id, cleaner_a)
    sibling = await api.get(
        f"{TASKS}/{task_a.id}/checklist", headers=auth_header(api, cleaner_a)
    )
    assert mine.status_code == 200
    assert sibling.status_code == 200, (
        "the `/checklist` baseline did not answer 200; this test compares two live responses "
        "and cannot tell you anything if one of them failed"
    )

    mine_names = {name.lower() for name in mine.headers}

    assert mine_names == BASELINE_RESPONSE_HEADERS, (
        f"the header set changed: {sorted(mine_names ^ BASELINE_RESPONSE_HEADERS)}. This is the "
        "half a sibling comparison cannot do — a verdict header stamped from the `APIRouter`, "
        "from `include_router` or from app-wide middleware lands on `/checklist` too, so the "
        "difference below would be empty while both routes leaked. If the app genuinely grows a "
        "global header, add it here on purpose."
    )
    extra = mine_names - {name.lower() for name in sibling.headers}
    assert not extra, (
        f"this route answers with headers its sibling does not: {sorted(extra)}. A header is a "
        "verdict channel (R3.2): the projection reports what is uploaded and adjudicates "
        "nothing. If a header is genuinely wanted here, it belongs on both read routes and in "
        "this assertion, deliberately."
    )


@pytest.mark.asyncio
async def test_an_optional_type_is_in_the_collection(api, task_a, cleaner_a):
    """R2.2 — the upload admits it, so the enumeration names it."""
    data = (await _get(api, task_a.id, cleaner_a)).json()["data"]

    assert {entry["photo_type"]: entry["required"] for entry in data} == {
        "kitchen": True,
        "before": False,
        "aftermath": True,
    }


@pytest.mark.asyncio
async def test_the_order_is_the_templates_own_and_not_sorted(api, task_a, cleaner_a):
    """R1.3 — the order the author declared, which is the order the work is done in."""
    data = (await _get(api, task_a.id, cleaner_a)).json()["data"]

    types = [entry["photo_type"] for entry in data]
    assert types == ["kitchen", "before", "aftermath"]
    assert types != sorted(types)


@pytest.mark.asyncio
async def test_a_template_declaring_no_photo_is_a_200_with_an_empty_collection(
    api, db_session, tenant_a, property_a, cleaner_a
):
    """R1.2 — "esta tarea no pide fotos" is an answer, and never a `404`."""
    template = await insert_template(db_session, tenant_a, required_photos=[])
    task = await insert_task(db_session, tenant_a, property_a, template, cleaner=cleaner_a)

    response = await _get(api, task.id, cleaner_a)

    assert response.status_code == 200, response.text
    assert response.json() == {"data": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", list(CleaningTaskStatus), ids=lambda s: s.value)
async def test_the_answer_does_not_depend_on_the_tasks_status(
    api, db_session, tenant_a, property_a, photo_template_a, cleaner_a, status
):
    """R1.4 — including before `IN_PROGRESS`, which is when the cleaner needs it.

    The upload itself is `409` outside `IN_PROGRESS`; knowing *what* to upload is not, and the
    whole point of the capability is that she can see the categories before starting.
    """
    task = await insert_task(
        db_session, tenant_a, property_a, photo_template_a, status=status, cleaner=cleaner_a
    )

    response = await _get(api, task.id, cleaner_a)

    assert response.status_code == 200, response.text
    assert len(response.json()["data"]) == 3


# --- the uploaded state --------------------------------------------------------------


@pytest.mark.asyncio
async def test_uploaded_flips_only_for_the_type_that_was_uploaded(
    api, db_session, task_a, cleaner_a
):
    """R3.1 — the fact of upload, read from `cleaning_photos` scoped to this task."""
    before = (await _get(api, task_a.id, cleaner_a)).json()["data"]
    assert all(entry["uploaded"] is False for entry in before)

    await _add_photo(db_session, task_a, cleaner_a, photo_type="before")

    after = (await _get(api, task_a.id, cleaner_a)).json()["data"]
    assert {entry["photo_type"]: entry["uploaded"] for entry in after} == {
        "kitchen": False,
        "before": True,
        "aftermath": False,
    }


@pytest.mark.asyncio
async def test_two_photos_of_one_type_are_still_one_entry(api, db_session, task_a, cleaner_a):
    """R3.1 — `uploaded` answers membership, and several photos of a type are deliberate.

    `cleaning_photos` has no uniqueness constraint on `(task_id, photo_type)` on purpose, so the
    projection has to collapse them rather than grow a row per photo.
    """
    await _add_photo(db_session, task_a, cleaner_a, photo_type="kitchen")
    await _add_photo(db_session, task_a, cleaner_a, photo_type="kitchen")

    data = (await _get(api, task_a.id, cleaner_a)).json()["data"]

    assert [entry["photo_type"] for entry in data] == ["kitchen", "before", "aftermath"]
    assert data[0]["uploaded"] is True


@pytest.mark.asyncio
async def test_a_photo_of_a_type_the_template_no_longer_declares_adds_no_entry(
    api, db_session, task_a, cleaner_a
):
    """R1.1 from the other side: driven by the template, never by the photos table."""
    await _add_photo(db_session, task_a, cleaner_a, photo_type="balcony")

    data = (await _get(api, task_a.id, cleaner_a)).json()["data"]

    assert [entry["photo_type"] for entry in data] == ["kitchen", "before", "aftermath"]


@pytest.mark.asyncio
async def test_the_body_carries_no_verdict_field(api, task_a, cleaner_a):
    """R3.2 — it reports what is filed and adjudicates nothing.

    The close is the only place PRD §11's clauses are applied; a `satisfied`/`can_complete` here
    would be a second point of application that could drift from it.

    **Matched on the KEYS, not on the raw body**, and the difference is not pedantry: `label` is
    text the tenant types, so a perfectly legitimate "Foto antes de que se complete la limpieza"
    would trip a substring search for `complete` and fail this test for a reason that has
    nothing to do with R3.2. The fixture below proves the narrowing did not gut the check — a
    key named `completed`, the likeliest drift because `ChecklistItemStateResponse` has one, is
    still caught.
    """
    data = (await _get(api, task_a.id, cleaner_a)).json()["data"]

    forbidden = {"satisfied", "can_complete", "canComplete", "completed", "missing", "complete"}
    for entry in data:
        assert not forbidden & set(entry), (
            f"the response grew a completion verdict: {sorted(forbidden & set(entry))}"
        )


@pytest.mark.asyncio
async def test_a_label_may_legitimately_contain_the_word_complete(
    api, db_session, tenant_a, property_a, cleaner_a
):
    """The other half of the test above: the narrowing has to admit real tenant text.

    A label is free text the property manager writes. If the guard above searched the raw body
    this request would fail, and the failure would look like a domain regression rather than
    like a template someone worded normally.
    """
    template = await insert_template(
        db_session,
        tenant_a,
        required_photos=[
            {"photo_type": "after", "label": "Antes de que se complete la limpieza",
             "required": True}
        ],
    )
    task = await insert_task(db_session, tenant_a, property_a, template, cleaner=cleaner_a)

    response = await _get(api, task.id, cleaner_a)

    assert response.status_code == 200, response.text
    assert response.json()["data"][0]["label"] == "Antes de que se complete la limpieza"


# --- what must not leak --------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_body_carries_nothing_of_the_template_beyond_the_three_fields(
    api, task_a, photo_template_a, cleaner_a
):
    """R4.4 — not the template's `id`, `name`, `property_id`, `active`, nor its raw `items`.

    Asserted against the real bytes: a projection that omits them is an intention, and a body
    that does not contain the strings is the guarantee.
    """
    body = (await _get(api, task_a.id, cleaner_a)).text

    assert str(photo_template_a.id) not in body
    assert TEMPLATE_NAME not in body
    assert str(photo_template_a.property_id) not in body
    assert "active" not in body
    assert "ITEM-QUE-NO-DEBE-SALIR" not in body
    assert "itemquenodebesalir" not in body


@pytest.mark.asyncio
async def test_the_forbidden_search_is_not_vacuous(api, task_a, photo_template_a, cleaner_a):
    """The test above only means something if those strings are really in the row it reads."""
    assert photo_template_a.name == TEMPLATE_NAME
    assert photo_template_a.items == TEMPLATE_ITEMS
    assert photo_template_a.property_id is not None
    assert photo_template_a.active is True


@pytest.mark.asyncio
async def test_a_stored_template_that_stops_parsing_does_not_name_itself(
    api, db_session, tenant_a, property_a, cleaner_a
):
    """R4.4 on the FAILURE path, which the 200-path test above cannot reach.

    `parse_template_content` interpolates its `template_id` into the `CleaningValidationError`
    message, and the error envelope carries `str(exc)` verbatim — so a read path that passes the
    id publishes it to whoever gets the 422. `CLEANER` holds no `READ_CLEANING_TEMPLATES`, which
    makes that the template identifier of a row she cannot fetch, and R4.4 names the `id` first
    among the things this response must not carry.

    The row is written straight through the model, as a corrupted stored template would be: the
    create endpoint validates, so this state is only reachable the ways it really happens — an
    older writer, a seed, a support script, or a limit lowered under rows that already exist.
    """
    broken = await insert_template(
        db_session, tenant_a, property_id=property_a.id, items=[], required_photos=PHOTOS
    )
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        broken,
        status=CleaningTaskStatus.CREATED,
        cleaner=cleaner_a,
    )

    response = await _get(api, task.id, cleaner_a)

    assert response.status_code == 422, (
        f"expected the stored row to fail parsing, got {response.status_code} — if the parser "
        "grew tolerant of empty `items` this test is no longer reaching the path it guards"
    )
    assert str(broken.id) not in response.text, (
        "the 422 names the template. R4.4 forbids this response publishing the template's `id`, "
        "and `parse_template_content` interpolates it only when a caller passes `template_id=`."
    )


@pytest.mark.asyncio
async def test_no_storage_key_or_photo_id_reaches_this_surface(
    api, db_session, task_a, cleaner_a
):
    """Rule 5 of `steering/security.md` — the internal object path is not this route's business.

    It reads `cleaning_photos` and answers a boolean, so nothing of the row but the fact should
    be able to travel; this pins that as a property of the body rather than of the schema.
    """
    photo = await _add_photo(db_session, task_a, cleaner_a, photo_type="kitchen")

    body = (await _get(api, task_a.id, cleaner_a)).text

    assert photo.storage_key not in body
    assert "tenants/" not in body
    assert str(photo.id) not in body


# --- the refusals --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_id_and_another_cleaners_task_are_byte_identical_404s(
    api, task_a, other_cleaner_a
):
    """R1.5, two of the three causes — compared as rendered bodies, not as status codes."""
    unknown = await _get(api, uuid.uuid4(), other_cleaner_a)
    foreign = await _get(api, task_a.id, other_cleaner_a)

    assert unknown.status_code == foreign.status_code == 404
    assert unknown.text == foreign.text
    assert foreign.json()["error"]["message"] == TASK_NOT_FOUND_MESSAGE


@pytest.mark.asyncio
async def test_another_tenants_task_is_the_same_404(api, task_b, cleaner_a):
    """R1.5, the third cause — the envelope's shape; the mechanism is proved at the bottom."""
    response = await _get(api, task_b.id, cleaner_a)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["message"] == TASK_NOT_FOUND_MESSAGE


@pytest.mark.asyncio
async def test_a_template_the_task_cannot_reach_is_a_404(
    api, db_session, task_a, template_b, cleaner_a
):
    """R1.6 — the task's template no longer resolves, so the same `404` the close answers.

    **Repointed rather than deleted, and that is not a workaround.**
    `cleaning_tasks.checklist_template_id` is `ON DELETE RESTRICT`, so a template a task
    references cannot be removed at all — the literal "deleted template" of R1.6 is unreachable
    while the task exists. What *is* reachable is a row the tenant-scoped read cannot return,
    and the sharpest instance of it is a template belonging to another tenant: the foreign key
    is satisfied (it does not know about tenants) while
    `SqlAlchemyCleaningChecklistTemplateRepository.get(tenant_id, ...)` answers `None`.

    **What this test does not prove**, corrected after the tenancy reviewer measured it: it is
    not evidence that the template repository's own `WHERE tenant_id` is load-bearing. This runs
    through the `api` fixture, whose session an authenticated request has already marked, and
    `cleaning_checklist_templates` *does* carry a `tenant_id` column — so the global loader
    criteria of `app/core/db.py` filter the row whether or not the adapter asks them to. The
    reviewer removed that filter and this test stayed green. What proves the adapter's own
    scoping is `test_the_template_read_is_scoped_on_an_unmarked_session` at the bottom of this
    file; what this one pins is the status and the envelope the caller sees.
    """
    from app.cleaning.infrastructure.models import CleaningTaskModel

    task = await db_session.get(CleaningTaskModel, task_a.id)
    task.checklist_template_id = template_b.id
    await db_session.flush()

    response = await _get(api, task_a.id, cleaner_a)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_the_404_uses_the_prd_error_envelope(api, cleaner_a):
    """PRD §23 — `{error: {code, message, details}}`, which the declared catalogue promises."""
    body = (await _get(api, uuid.uuid4(), cleaner_a)).json()

    assert set(body) == {"error"}
    assert set(body["error"]) >= {"code", "message"}


# --- who reaches it ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_role_without_the_read_permission_is_403(api, task_a, users_by_role_a):
    """R4.1 — `TECHNICIAN` holds no cleaning permission at all.

    The code and not just the status: `PasswordChangeRequiredError` also answers `403`, so a
    bare status assertion would keep passing if the shared user fixture ever started demanding a
    password change, leaving the RBAC gate untested while the suite stayed green.
    """
    response = await _get(api, task_a.id, users_by_role_a[UserRole.TECHNICIAN])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER],
    ids=["property_manager", "tenant_owner"],
)
async def test_a_manager_or_owner_reads_a_task_that_is_not_theirs(
    api, task_a, users_by_role_a, role
):
    """R4.1 — the three holders of `READ_CLEANING_TASKS` all reach it.

    `restrict_to_cleaner_id` is `None` for both of these roles, so the row-level rule does not
    apply and neither of them has to be the assigned cleaner.
    """
    response = await _get(api, task_a.id, users_by_role_a[role])

    assert response.status_code == 200, response.text
    assert len(response.json()["data"]) == 3


def test_the_cleaner_still_holds_no_template_permission() -> None:
    """R4.2 — the projection narrows, it does not grant.

    Read off `ROLE_PERMISSIONS` rather than from a request: the alternative this change rejected
    was giving `CLEANER` `READ_CLEANING_TEMPLATES` to resolve three fields of her own template,
    which would open the tenant's entire template catalogue. This fails the day someone does it.
    """
    from app.auth.domain.policy import ROLE_PERMISSIONS, Permission

    granted = ROLE_PERMISSIONS[UserRole.CLEANER]

    assert Permission.READ_CLEANING_TASKS in granted
    assert Permission.READ_CLEANING_TEMPLATES not in granted
    assert Permission.MANAGE_CLEANING_TEMPLATES not in granted


@pytest.mark.asyncio
async def test_the_cleaner_still_cannot_reach_the_template_catalogue_over_http(
    api, task_a, cleaner_a
):
    """R4.2 at the boundary, because the static check above is not the whole promise.

    Added after the QA reviewer pointed out that R4.2 rested entirely on a read of
    `ROLE_PERMISSIONS`: a dict can say the permission is absent while a route forgets to ask for
    it. The alternative this change rejected was giving `CLEANER` `READ_CLEANING_TEMPLATES` so
    she could resolve three fields of her own template — which would have opened the tenant's
    whole catalogue. This asserts the catalogue stays shut for the same caller, in the same
    session, who is allowed the projection.
    """
    allowed = await _get(api, task_a.id, cleaner_a)
    refused = await api.get(
        "/api/v1/cleaning-checklist-templates", headers=auth_header(api, cleaner_a)
    )

    assert allowed.status_code == 200, allowed.text
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_the_route_takes_no_query_parameter_that_could_widen_the_scope(
    api, task_a, other_cleaner_a
):
    """R4.3 — a regression guard, and worth being honest about what it is.

    It does **not** demonstrate that scope-widening is prevented by design: the handler declares
    no such parameter, and FastAPI discards unrecognised query arguments on every route whatever
    the scoping does, so this `404` is produced entirely by `_load_task`. The tenancy reviewer
    measured exactly that.

    It is kept because it becomes meaningful the day someone wires a `cleaner_id` in: at that
    point a parameter that is *honoured* turns this `404` into a `200`, and this is the test
    that says so. R4.3's live guarantee is elsewhere — the use case's signature test, and the
    fact that `tenant_id` reaches it only from `authenticated.context`.
    """
    response = await api.get(
        f"{TASKS}/{task_a.id}/photo-requirements",
        params={"cleaner_id": str(task_a.assigned_cleaner_id), "assigned_cleaner_id": "x"},
        headers=auth_header(api, other_cleaner_a),
    )

    assert response.status_code == 404


# --- what the contract has to say ----------------------------------------------------


def test_the_published_contract_states_the_relation_r2_3_requires() -> None:
    """R2.3, both directions — asserted because nothing else in the system reads these strings.

    A description is a *requirement* here: `cleaner-app` is written against the published
    operation, so a refactor that garbled these sentences would leave the relation between the
    two routes a coincidence the client has to discover. Asserted against the generated
    document, not the decorator, for the same reason.
    """
    document = build_openapi(create_app())
    paths = document["paths"]

    requirements = paths[f"{TASKS}/{{task_id}}/photo-requirements"]["get"]["description"]
    # Forward: absence from this collection is the upload's 404.
    assert "/cleaning-tasks/{task_id}/photos" in requirements
    assert "404" in requirements
    # And the two facts R2.1 separates are named as two.
    assert "required" in requirements

    upload_404 = paths[f"{TASKS}/{{task_id}}/photos"]["post"]["responses"]["404"][
        "description"
    ]
    # Reciprocal: the upload's 404 says where the declared types are read.
    assert "photo-requirements" in upload_404


def test_the_two_schema_names_do_not_add_a_third_module_collision() -> None:
    """D3 — a third `CleaningPhoto…` would mangle the two that survive by module today.

    `backend/openapi.json` already carries `app__cleaning__api__schemas__CleaningPhotoResponse`
    and `app__dashboard__api__schemas__CleaningPhotoResponse`, and those mangled names are what
    a frontend consumer writes by hand. This asserts the new pair entered the document under
    their plain names.
    """
    schemas = build_openapi(create_app())["components"]["schemas"]

    assert "PhotoRequirementStateResponse" in schemas
    assert "PhotoRequirementsResponse" in schemas
    assert not [name for name in schemas if name.endswith("__PhotoRequirementStateResponse")]
    assert not [name for name in schemas if name.endswith("__PhotoRequirementsResponse")]


def test_the_route_declares_only_the_404_it_can_reach() -> None:
    """D7 — no `409`, because R1.4 answers whatever the task's status.

    The catalogue is a claim about what this handler can answer; a `409` in it would advertise a
    refusal that cannot happen and would read as "this route needs the task to be in progress".
    """
    document = build_openapi(create_app())
    declared = set(
        document["paths"][f"{TASKS}/{{task_id}}/photo-requirements"]["get"]["responses"]
    )

    assert "404" in declared
    assert "409" not in declared


# --- the isolation proof, on an unmarked session -------------------------------------


@pytest.mark.asyncio
async def test_the_tenant_filter_is_load_bearing_on_an_unmarked_session(
    db_session, task_b, cleaner_b, tenant_a
):
    """Rule 1 of `steering/security.md`, proved rather than observed.

    Everything above runs through the `api` fixture, whose session an authenticated request has
    already marked with the caller's tenant — and under `bind_session_to_tenant` the listener of
    `app/core/db.py` filters every statement down to the `select` of a single column, so a
    repository that had forgotten its own `WHERE tenant_id` would still return nothing and the
    HTTP test would pass while the code was wrong.

    This one drives the use case with the **real** repositories over `db_session`, which is
    deliberately not bound, so the refusal it observes is produced by the query and not by the
    framework. `task_b` belongs to tenant B; `tenant_a` asks for it.
    """
    use_case = GetPhotoRequirementsUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(db_session),
        templates=SqlAlchemyCleaningChecklistTemplateRepository(db_session),
        photos=SqlAlchemyCleaningPhotoRepository(db_session),
    )

    with pytest.raises(CleaningTaskNotFoundError):
        await use_case.execute(
            tenant_id=tenant_a.id,
            task_id=task_b.id,
            actor=CleaningActor(user_id=uuid.uuid4(), role=UserRole.PROPERTY_MANAGER),
        )


@pytest.mark.asyncio
async def test_the_unmarked_probe_is_not_vacuous(db_session, task_b, cleaner_b, tenant_b):
    """The test above proves nothing unless the same call succeeds for the right tenant.

    Without this, deleting the whole route would leave that assertion green.
    """
    use_case = GetPhotoRequirementsUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(db_session),
        templates=SqlAlchemyCleaningChecklistTemplateRepository(db_session),
        photos=SqlAlchemyCleaningPhotoRepository(db_session),
    )

    views = await use_case.execute(
        tenant_id=tenant_b.id,
        task_id=task_b.id,
        actor=CleaningActor(user_id=cleaner_b.id, role=UserRole.CLEANER),
    )

    # `template_b` carries `STANDARD_PHOTOS`: one required type, `kitchen`.
    assert [view.photo_type for view in views] == ["kitchen"]


@pytest.mark.asyncio
async def test_the_photo_join_is_the_only_thing_keeping_another_tenants_photos_out(
    db_session, tenant_a, tenant_b, task_b, cleaner_b
):
    """Rule 1 on the one table in this change that has no `tenant_id` and no listener behind it.

    `cleaning_photos` is scoped transitively through `cleaning_task_id`, so the `JOIN` inside
    `uploaded_photo_types` is the entire mechanism — the global loader criteria of
    `app/core/db.py` never reach it.

    **The probe asks for tenant B's task under tenant A, on the same `task_id`.** An earlier
    version of this test planted the photo on one task and queried a *different* one, and both
    the security and the tenancy reviewers measured it vacuous: task ids are globally unique, so
    `WHERE cleaning_task_id = :task_id` alone excluded the row and deleting the tenant predicate
    left the test green — the very mutant its docstring claimed to kill. Holding the task id
    fixed and varying only the tenant leaves the `JOIN` as the only thing that can produce the
    empty answer.
    """
    await _add_photo(db_session, task_b, cleaner_b, photo_type="kitchen")
    photos = SqlAlchemyCleaningPhotoRepository(db_session)

    assert await photos.uploaded_photo_types(tenant_b.id, task_b.id) == frozenset({"kitchen"})
    assert await photos.uploaded_photo_types(tenant_a.id, task_b.id) == frozenset()


@pytest.mark.asyncio
async def test_the_template_read_is_scoped_on_an_unmarked_session(
    db_session, tenant_a, template_b
):
    """Rule 1 for the template read, which the HTTP `404` above cannot prove.

    Over HTTP the global listener filters this row anyway, so the adapter's own `WHERE
    tenant_id` could be deleted with the suite green — the tenancy reviewer measured it. Here
    the session is unmarked and the adapter is driven directly, so the `None` can only come from
    its own predicate. It matters because the row this guards carries the tenant's `label` text:
    a template read that crossed tenants would publish another tenant's labels under a `200`.
    """
    templates = SqlAlchemyCleaningChecklistTemplateRepository(db_session)

    assert await templates.get(tenant_b_id := template_b.tenant_id, template_b.id) is not None
    assert tenant_b_id != tenant_a.id
    assert await templates.get(tenant_a.id, template_b.id) is None
