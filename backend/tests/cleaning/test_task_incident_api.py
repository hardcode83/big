"""`POST /api/v1/cleaning-tasks/{task_id}/incidents`, end to end over ASGI (R1, R2, R4).

What only this level can show:

* **The accepted field set is a contract, not an intention.** `extra="forbid"` is a line in a
  model; a `422` for a body carrying `source` is the guarantee. R4.5 asks for exactly this — that
  adding a field becomes a deliberate act rather than a drift — so the rejected names are
  enumerated one by one instead of being described.
* **The `403` arrives before the task is resolved, and writes nothing.** Stated that way and not
  as "before the database is touched", which the security panel of section 6 showed is false of
  every authenticated route here: `get_authenticated_request` reads `users` — that read *is* the
  authentication, and it is what re-reads the persisted role — before `require(...)` evaluates
  the permission at all. What the wire can show, and what the anti-probe guarantee needs, is that
  an unauthorised caller gets the same `403` for a real task and for an invented id.
* **The four `404`s are byte-identical.** Comparing rendered bodies is the only way to prove the
  route is not a probe; the use-case tests can only compare exception messages.
* **What actually landed in `incidents`.** The row is read back to check `source = CLEANER`, the
  reporter, the task link and — the negative that matters — that no guest token was written.

The per-branch rules are pinned in `test_task_incident_use_case.py`; here they are checked to
survive the wiring.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import TASK_NOT_FOUND_MESSAGE
from app.maintenance.domain.enums import IncidentSource, IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel
from tests.cleaning.conftest import (
    auth_header,
    insert_property,
    insert_task,
    insert_template,
)

TASKS = "/api/v1/cleaning-tasks"
TITLE = "Caldera rota"
DESCRIPTION = "No sale agua caliente en el baño del piso."
BODY = {"title": TITLE, "description": DESCRIPTION}

#: The three keys of the acknowledgement, as the wire must carry them (R4.4).
EXPECTED_KEYS = {"id", "status", "created_at"}

#: Everything R1.3 names, plus the two the acknowledgement must not echo. Each one is a field
#: some caller might plausibly try to set, and every one of them is derived or sealed.
FORBIDDEN_REQUEST_FIELDS = (
    "property_id",
    "reservation_id",
    "tenant_id",
    "source",
    "category",
    "severity",
    "status",
    "assigned_technician_id",
    "estimated_cost",
    "approved_cost",
    "final_cost",
    "cleaning_task_id",
    "reported_by_user_id",
    "reported_by_guest_token",
)


async def _insert_user(session, tenant, role: UserRole) -> UserModel:
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=role.value.title(),
        email=f"{role.value.lower()}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x" * 60,
        role=role,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def cleaner_a(db_session, tenant_a):
    return await _insert_user(db_session, tenant_a, UserRole.CLEANER)


@pytest_asyncio.fixture
async def other_cleaner_a(db_session, tenant_a):
    """A second cleaner of the **same** tenant — the R2.2 case tenant scoping cannot catch."""
    return await _insert_user(db_session, tenant_a, UserRole.CLEANER)


@pytest_asyncio.fixture
async def manager_a(db_session, tenant_a):
    """`PROPERTY_MANAGER` holds `MANAGE_CLEANING_TASKS`, **not** `EXECUTE_CLEANING_TASKS`."""
    return await _insert_user(db_session, tenant_a, UserRole.PROPERTY_MANAGER)


@pytest_asyncio.fixture
async def cleaner_b(db_session, tenant_b):
    return await _insert_user(db_session, tenant_b, UserRole.CLEANER)


@pytest_asyncio.fixture
async def task_a(db_session, tenant_a, property_a, template_a, cleaner_a):
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner_a,
    )
    await db_session.flush()
    return task


async def _report(api, task_id, user, body=None):
    return await api.post(
        f"{TASKS}/{task_id}/incidents",
        json=BODY if body is None else body,
        headers=auth_header(api, user),
    )


async def _incidents(session):
    return list((await session.execute(select(IncidentModel))).scalars().all())


# --- the happy path, and what actually landed --------------------------------------------


@pytest.mark.asyncio
async def test_the_assigned_cleaner_gets_a_201_with_the_three_field_acknowledgement(
    api, db_session, task_a, cleaner_a
) -> None:
    """R1.1, R4.4."""
    response = await _report(api, task_a.id, cleaner_a)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == EXPECTED_KEYS
    assert body["status"] == IncidentStatus.OPEN.value
    uuid.UUID(body["id"])
    assert body["created_at"]


@pytest.mark.asyncio
async def test_the_created_row_is_sealed_cleaner_and_linked_to_the_task(
    api, db_session, task_a, cleaner_a, property_a
) -> None:
    """R3.1, R3.3, R4.3 — read back from `incidents`, not inferred from the response.

    The response deliberately says almost nothing, so the only way to check what was written is
    to look at the row.
    """
    response = await _report(api, task_a.id, cleaner_a)
    assert response.status_code == 201, response.text

    rows = await _incidents(db_session)
    assert len(rows) == 1
    incident = rows[0]
    assert incident.source is IncidentSource.CLEANER
    assert incident.reported_by_user_id == cleaner_a.id
    assert incident.cleaning_task_id == task_a.id
    assert incident.property_id == property_a.id
    assert incident.tenant_id == task_a.tenant_id
    assert incident.status is IncidentStatus.OPEN
    # Not an anonymous surface: the guest-token column belongs to the portal and stays NULL.
    assert incident.reported_by_guest_token is None
    assert incident.title == TITLE
    assert incident.description == DESCRIPTION


# --- the field sets, which R4.5 asks to be pinned -----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("field", FORBIDDEN_REQUEST_FIELDS)
async def test_a_body_carrying_a_derived_or_sealed_field_is_refused(
    api, db_session, task_a, cleaner_a, field: str
) -> None:
    """R1.3, R4.5. Rejected rather than ignored, so a caller cannot believe it was accepted.

    Each of these is either derived from the resolved task (`property_id`, `cleaning_task_id`),
    taken from the token (`tenant_id`, `reported_by_user_id`), sealed by the writer (`source`),
    or the classifier's to fill in (`category`, `severity`, `status`, the costs).
    """
    response = await _report(api, task_a.id, cleaner_a, {**BODY, field: str(uuid.uuid4())})

    assert response.status_code == 422, response.text
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "why"),
    [
        ({"title": TITLE}, "description missing"),
        ({"description": DESCRIPTION}, "title missing"),
        ({"title": "", "description": DESCRIPTION}, "empty title"),
        ({"title": "   ", "description": DESCRIPTION}, "whitespace-only title"),
        ({"title": TITLE, "description": ""}, "empty description"),
        ({"title": "x" * 301, "description": DESCRIPTION}, "title over 300"),
        ({"title": TITLE, "description": "x" * 5001}, "description over 5000"),
        ({"title": "boiler\x00", "description": DESCRIPTION}, "NUL the database cannot store"),
        ({"title": TITLE, "description": "leak\x00"}, "NUL in the description"),
    ],
)
async def test_a_body_that_is_not_two_storable_non_empty_strings_is_refused(
    api, db_session, task_a, cleaner_a, body: dict, why: str
) -> None:
    """R1.3 and R5.1 at the boundary.

    The two `\\x00` cases are the ones that matter beyond ordinary validation: without the
    storable-text guard they reach asyncpg and surface as an undeclared `500`, which is the
    failure the section-7 panel of `guest-portal-api` measured twice on these columns.
    """
    response = await _report(api, task_a.id, cleaner_a, body)

    assert response.status_code == 422, f"{why}: {response.text}"
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_the_acknowledgement_never_carries_the_incidents_other_fields(
    api, task_a, cleaner_a
) -> None:
    """R4.4's negative half, on the serialised body rather than on the model.

    `description` is on this list for a reason of its own: echoing it back would be one more
    place a rule-11 sink's value travels to, for nothing the caller does not already have.
    """
    response = await _report(api, task_a.id, cleaner_a)

    assert response.status_code == 201, response.text
    body = response.json()
    for absent in (
        "category",
        "severity",
        "ai_summary",
        "ai_classification",
        "reported_by_guest_token",
        "reported_by_user_id",
        "description",
        "title",
        "property_id",
        "cleaning_task_id",
        "tenant_id",
    ):
        assert absent not in body, f"{absent} leaked into the acknowledgement"
    assert DESCRIPTION not in response.text


# --- who may call it, and who may not (R1.6, R2.1) -----------------------------------------


@pytest.mark.asyncio
async def test_without_a_token_it_is_401(api, db_session, task_a) -> None:
    response = await api.post(f"{TASKS}/{task_a.id}/incidents", json=BODY)

    assert response.status_code == 401, response.text
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_a_manager_is_403_and_nothing_is_written(
    api, db_session, task_a, manager_a
) -> None:
    """R2.1, and the reason there is no new permission.

    `EXECUTE_CLEANING_TASKS` is the cleaner's alone; a `PROPERTY_MANAGER` holds
    `MANAGE_CLEANING_TASKS`, which is a different thing.

    **What the empty `incidents` table proves, and what it does not.** It proves no row was
    written. It does *not* prove the refusal preceded every query — a `403` raised after a failed
    lookup would leave the table just as empty, and the security panel of section 6 showed the
    authentication read genuinely does come first. The ordering is proved by the next test
    instead, where an id that does not exist still answers `403` rather than `404`.
    """
    response = await _report(api, task_a.id, manager_a)

    assert response.status_code == 403, response.text
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_a_manager_is_403_even_for_a_task_that_does_not_exist(
    api, db_session, manager_a
) -> None:
    """**This is the test that proves the ordering**, and the one above cannot.

    An id that does not exist answers `403` and not `404`, which is only possible if the
    permission gate runs before the task is resolved. A caller without the permission therefore
    cannot use the route to learn which task ids exist — the refusal is identical either way.
    """
    response = await _report(api, uuid.uuid4(), manager_a)

    assert response.status_code == 403, response.text
    assert await _incidents(db_session) == []


# --- the four 404s, byte for byte (R2.3) ---------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_task_is_404(api, db_session, cleaner_a) -> None:
    response = await _report(api, uuid.uuid4(), cleaner_a)

    assert response.status_code == 404, response.text
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_another_cleaners_task_of_the_same_tenant_is_404(
    api, db_session, task_a, other_cleaner_a
) -> None:
    """R2.2 over the wire: tenant scoping alone would let this through."""
    response = await _report(api, task_a.id, other_cleaner_a)

    assert response.status_code == 404, response.text
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_another_tenants_task_is_404(
    api, db_session, tenant_b, property_b, template_b, cleaner_a, cleaner_b
) -> None:
    """The cross-tenant path through the real stack, where the session **is** tenant-marked.

    Unlike the use-case test — which runs unmarked on purpose so the repository's own
    `WHERE tenant_id` is what refuses — this one exercises the whole defence together, which is
    what a caller actually meets.
    """
    task = await insert_task(
        db_session,
        tenant_b,
        property_b,
        template_b,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner_b,
    )
    await db_session.flush()

    response = await _report(api, task.id, cleaner_a)

    assert response.status_code == 404, response.text
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_a_task_whose_property_is_not_this_tenants_is_404(
    api, db_session, tenant_a, tenant_b, template_a, cleaner_a
) -> None:
    """R2.3's fourth path, which the schema permits: `cleaning_tasks.property_id` is a
    single-column foreign key, so a task can point outside its own tenant."""
    foreign_property = await insert_property(db_session, tenant_b, code="AJENA3")
    task = await insert_task(
        db_session,
        tenant_a,
        foreign_property,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner_a,
    )
    await db_session.flush()

    response = await _report(api, task.id, cleaner_a)

    assert response.status_code == 404, response.text
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
async def test_the_404_body_uses_the_prd_error_envelope(
    api, db_session, cleaner_a
) -> None:
    """R1.6 for the status this route declares most often, which the envelope test below skips.

    Raised by the QA panel of section 6: `test_every_refusal_uses_the_prd_error_envelope` covers
    the `409` and the `422`, and the byte-identity test compares four `404`s to each other —
    which would stay green if all four were malformed in the same way. The envelope for this
    status came from a shared handler and was pinned nowhere in this file.
    """
    response = await _report(api, uuid.uuid4(), cleaner_a)

    assert response.status_code == 404, response.text
    envelope = response.json()
    assert set(envelope) == {"error"}
    assert set(envelope["error"]) >= {"code", "message"}
    assert envelope["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_the_four_404_bodies_are_byte_identical(
    api, db_session, tenant_a, tenant_b, property_a, property_b, template_a, template_b,
    cleaner_a, other_cleaner_a, cleaner_b,
) -> None:
    """R2.3 as the property it is: the route must not work as a probe.

    Comparing the **rendered bodies** and not the status codes — four `404`s whose messages
    differ would still tell an attacker which of the four situations they were in, one layer
    below the code.
    """
    mine_but_theirs = await insert_task(
        db_session, tenant_a, property_a, template_a,
        status=CleaningTaskStatus.IN_PROGRESS, cleaner=other_cleaner_a,
    )
    other_tenant = await insert_task(
        db_session, tenant_b, property_b, template_b,
        status=CleaningTaskStatus.IN_PROGRESS, cleaner=cleaner_b,
    )
    foreign_property = await insert_property(db_session, tenant_b, code="AJENA4")
    unresolvable = await insert_task(
        db_session, tenant_a, foreign_property, template_a,
        status=CleaningTaskStatus.IN_PROGRESS, cleaner=cleaner_a,
    )
    await db_session.flush()

    bodies = set()
    for task_id in (uuid.uuid4(), mine_but_theirs.id, other_tenant.id, unresolvable.id):
        response = await _report(api, task_id, cleaner_a)
        assert response.status_code == 404, response.text
        bodies.add(response.text)

    assert len(bodies) == 1, f"the four refusals are distinguishable: {bodies}"
    assert TASK_NOT_FOUND_MESSAGE in bodies.pop()


# --- the 409, and the envelope (R1.6, R2.5) ------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        CleaningTaskStatus.COMPLETED,
        CleaningTaskStatus.REJECTED,
        CleaningTaskStatus.CANCELLED,
    ],
)
async def test_a_terminal_task_is_409(
    api, db_session, tenant_a, property_a, template_a, cleaner_a, status
) -> None:
    """R2.5 over the wire. PRD §12 says «durante checklist»."""
    task = await insert_task(
        db_session, tenant_a, property_a, template_a, status=status, cleaner=cleaner_a
    )
    await db_session.flush()

    response = await _report(api, task.id, cleaner_a)

    assert response.status_code == 409, response.text
    assert await _incidents(db_session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        CleaningTaskStatus.ASSIGNED,
        CleaningTaskStatus.ACCEPTED,
        CleaningTaskStatus.IN_PROGRESS,
    ],
)
async def test_every_live_status_may_report(
    api, db_session, tenant_a, property_a, template_a, cleaner_a, status
) -> None:
    task = await insert_task(
        db_session, tenant_a, property_a, template_a, status=status, cleaner=cleaner_a
    )
    await db_session.flush()

    response = await _report(api, task.id, cleaner_a)

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected"),
    [(BODY, 409), ({"title": "", "description": DESCRIPTION}, 422)],
)
async def test_every_refusal_uses_the_prd_error_envelope(
    api, db_session, tenant_a, property_a, template_a, cleaner_a, body, expected
) -> None:
    """R1.6 — `{error:{code,message,details}}` of PRD §23, on the statuses this route declares."""
    task = await insert_task(
        db_session, tenant_a, property_a, template_a,
        status=CleaningTaskStatus.COMPLETED, cleaner=cleaner_a,
    )
    await db_session.flush()

    response = await _report(api, task.id, cleaner_a, body)

    assert response.status_code == expected, response.text
    envelope = response.json()
    assert set(envelope) == {"error"}
    assert set(envelope["error"]) >= {"code", "message"}


def test_no_creation_route_appears_under_the_incidents_prefix() -> None:
    """R1.2, and the reason this route hangs off the task rather than off the incident.

    `specs/maintenance.md` R8 says that module NEVER SHALL expose a **creation** route for
    incidents, and this change has to leave that true. It does by construction: the subject of
    the new route is the cleaning task, so it lives under `/cleaning-tasks/{id}/incidents` and
    the eleven routes under `/api/v1/incidents` are untouched.

    Read off the generated **contract** rather than asserted in prose, because "we did not add
    one" is exactly the kind of claim that rots the next time somebody needs a quick endpoint.
    The OpenAPI document and not `app.routes`: this application mounts its routers as
    sub-applications, so the flat route list does not contain the paths.
    """
    from app.main import create_app

    paths = create_app().openapi()["paths"]

    assert "post" not in paths.get("/api/v1/incidents", {}), (
        "a POST /api/v1/incidents appeared: R1.2 and specs/maintenance.md R8 both say the "
        "creation surface does not live in that module"
    )
    # And the one this change does add is where R1.2 puts it.
    assert "post" in paths["/api/v1/cleaning-tasks/{task_id}/incidents"]


# --- R6: the coupling between reporting and closing ----------------------------------------


@pytest.mark.asyncio
async def test_the_incident_she_reports_is_the_row_that_blocks_a_later_close(
    api, db_session, tenant_a, property_a, template_a, cleaner_a
) -> None:
    """R6.2 and R6.4 — the join this change creates, against the real blocking query.

    **What each level owns, so this test claims no more than it proves.** The entity halves are
    pinned in `test_task_lifecycle.py`: the incident is born `MEDIUM`, becomes `CRITICAL` through
    `classify`, and the refusal message never names it. The completion mechanics — a `409` from
    `POST /complete` when the property has an unresolved critical — are owned by
    `test_tasks_api.py::test_a_critical_incident_blocks_completion`, which drives the whole
    assign→accept→start→checklist→photo flow to get there.

    What neither can show is the link this change introduces: the row the **new route** writes is
    the row `SqlAlchemyBlockingIncidentQuery` reads. That is what this asserts, against the real
    adapter and the real row:

    * while the incident is `MEDIUM` the query says `False` — R6.2's declared behaviour, and the
      reason reporting does not lock the cleaner out of finishing the task she reported from;
    * once the classifier raises it to `CRITICAL` the same row makes it `True`, and the
      completion clause does the rest.
    """
    from app.cleaning.infrastructure.repositories import SqlAlchemyBlockingIncidentQuery
    from app.maintenance.domain.enums import IncidentSeverity

    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner_a,
    )
    await db_session.flush()
    query = SqlAlchemyBlockingIncidentQuery(db_session)

    assert await query.has_unresolved_critical(tenant_a.id, property_a.id) is False

    response = await _report(api, task.id, cleaner_a)
    assert response.status_code == 201, response.text

    rows = await _incidents(db_session)
    assert len(rows) == 1
    incident = rows[0]
    assert incident.severity is IncidentSeverity.MEDIUM, (
        "born MEDIUM is what makes R6.2 true: a default of CRITICAL would lock her out of "
        "closing the very task she reported from"
    )
    assert incident.property_id == property_a.id

    # R6.2: reporting, on its own, blocks nothing.
    assert await query.has_unresolved_critical(tenant_a.id, property_a.id) is False

    # The classifier raises it — the job of `maintenance` R3, simulated at the row because this
    # change deliberately does not classify inside the request that creates the incident (R3.2).
    incident.severity = IncidentSeverity.CRITICAL
    await db_session.flush()

    # R6.4: now the same row blocks, and it does so for the whole property (R6.1) — which is why
    # the incident's own `cleaning_task_id` plays no part in this answer.
    assert await query.has_unresolved_critical(tenant_a.id, property_a.id) is True
    assert await query.has_unresolved_critical(tenant_a.id, uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_a_critical_incident_of_another_task_on_the_property_still_blocks(
    api, db_session, tenant_a, property_a, template_a, cleaner_a
) -> None:
    """R6.1, behaviourally — the guard the structural ones cannot be.

    The QA panel of section 9 mutated the adapter to filter by `cleaning_task_id` instead of
    `property_id` — the narrowing D11 rejects — and showed the source-shape guards can miss it:
    the port keeps its arity, the gatherer keeps its two arguments, and only the `WHERE` moves.
    This is what catches that, because it asserts the invariant itself rather than the shape of
    the code implementing it.

    A `CRITICAL` incident that belongs to a **different** cleaning of the same property must
    still block. Narrowing the clause to the task would make this `False`, which is precisely
    why the proposal calls it a relaxation and sends it to its own change: a `CRITICAL` opened
    by a guest — with no `cleaning_task_id` at all — would stop blocking too.
    """
    from app.cleaning.infrastructure.repositories import SqlAlchemyBlockingIncidentQuery
    from app.maintenance.domain.enums import IncidentSeverity

    reported_from = await insert_task(
        db_session, tenant_a, property_a, template_a,
        status=CleaningTaskStatus.IN_PROGRESS, cleaner=cleaner_a,
    )
    await db_session.flush()

    assert (await _report(api, reported_from.id, cleaner_a)).status_code == 201
    rows = await _incidents(db_session)
    assert len(rows) == 1
    rows[0].severity = IncidentSeverity.CRITICAL
    await db_session.flush()

    # A different cleaning of the same flat. Its own id is nowhere near the incident.
    another_cleaning = await insert_task(
        db_session, tenant_a, property_a, template_a,
        status=CleaningTaskStatus.IN_PROGRESS, cleaner=cleaner_a,
    )
    await db_session.flush()
    assert rows[0].cleaning_task_id == reported_from.id
    assert rows[0].cleaning_task_id != another_cleaning.id

    blocked = await SqlAlchemyBlockingIncidentQuery(db_session).has_unresolved_critical(
        tenant_a.id, another_cleaning.property_id
    )

    assert blocked is True, (
        "the blocking clause stopped covering the whole property: R6.1 keeps it property-scoped "
        "because narrowing it to the task relaxes the invariant"
    )


@pytest.mark.asyncio
async def test_she_reports_the_classifier_raises_it_and_her_own_close_is_refused(
    api, db_session, tenant_a, property_a, template_a, users_by_role_a, cleaner_a
) -> None:
    """R6.4's sentence, through the real surfaces, in one test.

    The QA panel of section 9 judged the earlier composition a technicality, and it was right:
    three tests each proved one leg and none drove the journey R6.4 actually names — *she*
    reports, the classifier raises it, and **her own** `complete()` is refused. This is that
    journey, end to end over ASGI: the incident is created by the new route, not inserted; it
    starts `MEDIUM`; and the close that fails is on the very task she reported from.

    The template is **not** relaxed to skip the checklist and the photo — `test_tasks_api.py`
    says why in `_upload_photo`'s own docstring, and a fixture edited to avoid them would delete
    the coverage of the clauses that run *before* the incident one. So the flow is the real one:
    assign, accept, start, report, tick, photograph, then close.
    """
    from app.maintenance.domain.enums import IncidentSeverity
    from app.properties.domain.enums import PropertyOperationalState

    JPEG = b"\xff\xd8\xff" + b"\x00" * 64
    cleaner = auth_header(api, cleaner_a)
    manager = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    property_a.current_operational_state = PropertyOperationalState.AWAITING_CLEANING
    db_session.add(property_a)
    task = await insert_task(db_session, tenant_a, property_a, template_a)
    await db_session.flush()

    assigned = await api.patch(
        f"{TASKS}/{task.id}",
        json={"assigned_cleaner_id": str(cleaner_a.id)},
        headers=manager,
    )
    assert assigned.status_code == 200, assigned.text
    assert (await api.post(f"{TASKS}/{task.id}/accept", headers=cleaner)).status_code == 200
    assert (await api.post(f"{TASKS}/{task.id}/start", headers=cleaner)).status_code == 200

    # 1. She reports, from the task she is working on, through the route this change adds.
    reported = await _report(api, task.id, cleaner_a)
    assert reported.status_code == 201, reported.text
    rows = await _incidents(db_session)
    assert len(rows) == 1
    incident = rows[0]
    assert incident.severity is IncidentSeverity.MEDIUM
    assert incident.cleaning_task_id == task.id

    # 2. She finishes the work: every required item, and the required photo.
    for item in ("kitchen", "bathroom"):
        ticked = await api.post(
            f"{TASKS}/{task.id}/checklist/{item}/complete", headers=cleaner
        )
        assert ticked.status_code == 204, ticked.text
    photo = await api.post(
        f"{TASKS}/{task.id}/photos",
        data={"photo_type": "kitchen"},
        files={"file": ("photo.jpg", JPEG, "image/jpeg")},
        headers=cleaner,
    )
    assert photo.status_code == 201, photo.text

    # 3. The classifier raises it — `maintenance` R3's job, on its own tick.
    incident.severity = IncidentSeverity.CRITICAL
    await db_session.flush()

    # 4. Her own close is refused, and the body names the cause and nothing else.
    blocked = await api.post(f"{TASKS}/{task.id}/complete", headers=cleaner)

    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["message"] == (
        "An unresolved CRITICAL incident blocks completing this cleaning"
    )
    body = blocked.text
    assert str(incident.id) not in body
    assert TITLE not in body
    assert DESCRIPTION not in body
