"""Who may reach the thirteen routes, and what they see when they do (R5.2, R5.3, R5.4).

This is the file the RBAC of design D13 is proved in. `tests/auth/test_policy.py` fixes the
role × permission matrix; what it cannot show is that each route hangs off the permission it
should, and that the row-level restriction of R5.3 survives the trip through HTTP.
"""

import uuid

import pytest

from app.maintenance.domain.enums import IncidentStatus, OwnerApprovalStatus
from tests.maintenance.conftest import (  # noqa: F401
    _user,
    api,
    auth_header,
    make_approval,
    make_incident,
    world,
)

pytestmark = pytest.mark.asyncio

INCIDENTS = "/api/v1/incidents"
APPROVALS = "/api/v1/owner-approvals"

#: Every route of D14, as (method, path template). The path is formatted with one incident
#: id, so a test can walk the whole surface for one role in one loop.
ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", INCIDENTS),
    ("GET", INCIDENTS + "/{incident_id}"),
    # `tech-incident-context` R4.1/R4.7. It belongs in this census and not only in its own
    # file: a route left out of a list that claims to be "every route of D14" is how the
    # `CLEANER`-refused and anonymous-refused sweeps stop covering the surface.
    ("GET", INCIDENTS + "/{incident_id}/context"),
    ("POST", INCIDENTS + "/{incident_id}/classify"),
    ("PATCH", INCIDENTS + "/{incident_id}"),
    ("POST", INCIDENTS + "/{incident_id}/assign"),
    ("POST", INCIDENTS + "/{incident_id}/accept"),
    # `tech-cycle-completion` R1.6. In this census for the reason `context` is: a route left
    # out of a list that claims to be "every route of D14" is how the `CLEANER`-refused and
    # anonymous-refused sweeps quietly stop covering the surface.
    ("POST", INCIDENTS + "/{incident_id}/reject"),
    ("POST", INCIDENTS + "/{incident_id}/en-route"),
    ("POST", INCIDENTS + "/{incident_id}/wait-parts"),
    ("POST", INCIDENTS + "/{incident_id}/resume"),
    ("POST", INCIDENTS + "/{incident_id}/resolve"),
    ("POST", INCIDENTS + "/{incident_id}/cancel"),
)

_BODIES: dict[str, dict] = {
    "/assign": {"technician_id": "00000000-0000-0000-0000-000000000001"},
    "/resolve": {"final_cost": "10.00"},
}


def _body(path: str) -> dict:
    for suffix, payload in _BODIES.items():
        if path.endswith(suffix):
            return payload
    return {}


async def _call(api, method: str, path: str, headers: dict):
    return await api.request(method, path, json=_body(path) or None, headers=headers)


async def test_a_cleaner_is_refused_on_every_route(api, world, db_session) -> None:
    """R5.4: "NEVER SHALL exponer estas rutas al rol `CLEANER`". Structural rather than
    checked per route — the role holds none of the four permissions (D13).

    **Still true after `cleaner-incident-report`, and worth saying so here.** That change gives
    a `CLEANER` her first incident-related surface, so a reader could reasonably wonder whether
    this test survived it. It does, untouched: the alta lives under
    `POST /api/v1/cleaning-tasks/{task_id}/incidents`, gated on `EXECUTE_CLEANING_TASKS`, whose
    subject is the cleaning task. None of the four permissions of *this* module moved, and every
    route below is still a `403` for her — which is exactly why that change could be built
    without reopening R5.4."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    approval = await make_approval(db_session, world, incident.id)
    cleaner = await _user(db_session, world.tenant, "CLEANER")
    headers = auth_header(api, cleaner)

    for method, template in ROUTES:
        response = await _call(
            api, method, template.format(incident_id=incident.id), headers
        )
        assert response.status_code == 403, f"{method} {template}"

    respond = await api.post(
        f"{APPROVALS}/{approval.id}/respond",
        json={"status": OwnerApprovalStatus.APPROVED.value},
        headers=headers,
    )
    assert respond.status_code == 403


async def test_an_anonymous_caller_is_refused_on_every_route(api, world, db_session) -> None:
    """R5.4's other half: there is no anonymous door into this module. The guest portal is
    the only surface that creates an incident without a session, and it is not here."""
    incident = await make_incident(db_session, world)

    for method, template in ROUTES:
        response = await _call(api, method, template.format(incident_id=incident.id), {})
        assert response.status_code == 401, f"{method} {template}"


async def test_a_guest_portal_token_reaches_nothing(api, world, db_session) -> None:
    """A bearer of a portal link is not an `AuthenticatedRequest`: `require(...)` only
    accepts the user JWT, so the token is simply not a credential here."""
    incident = await make_incident(db_session, world)
    headers = {"Authorization": "Bearer a-guest-portal-token-not-a-jwt"}

    response = await api.get(f"{INCIDENTS}/{incident.id}", headers=headers)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("path", "method"),
    [
        (INCIDENTS + "/{incident_id}/classify", "POST"),
        (INCIDENTS + "/{incident_id}", "PATCH"),
        (INCIDENTS + "/{incident_id}/assign", "POST"),
        (INCIDENTS + "/{incident_id}/cancel", "POST"),
    ],
)
async def test_a_technician_cannot_manage(
    api, world, db_session, path: str, method: str
) -> None:
    """R5.2: "NEVER SHALL concederle nada más". Triage, assignment and cancellation are the
    manager's."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    response = await _call(
        api,
        method,
        path.format(incident_id=incident.id),
        auth_header(api, world.technician),
    )

    assert response.status_code == 403


async def test_an_owner_can_read_but_not_execute(api, world, db_session) -> None:
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    headers = auth_header(api, world.owner)

    assert (await api.get(INCIDENTS, headers=headers)).status_code == 200
    assert (
        await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=headers)
    ).status_code == 403


async def test_only_the_owner_answers_an_approval(api, world, db_session) -> None:
    """R2.6, at the permission layer this time."""
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)
    payload = {"status": OwnerApprovalStatus.APPROVED.value}

    for user in (world.manager, world.technician):
        response = await api.post(
            f"{APPROVALS}/{approval.id}/respond",
            json=payload,
            headers=auth_header(api, user),
        )
        assert response.status_code == 403


# --- The row-level restriction over HTTP (R5.3) -----------------------------------------


async def _assign_to(api, world, incident_id, technician) -> None:
    response = await api.post(
        f"{INCIDENTS}/{incident_id}/assign",
        json={"technician_id": str(technician.id)},
        headers=auth_header(api, world.manager),
    )
    assert response.status_code == 200


async def test_a_technician_lists_only_their_own(api, world, db_session) -> None:
    mine = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await _assign_to(api, world, mine.id, world.technician)
    theirs = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await _assign_to(api, world, theirs.id, world.other_technician)

    response = await api.get(INCIDENTS, headers=auth_header(api, world.technician))

    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(mine.id)]
    assert body["total"] == 1


async def test_an_incident_of_another_technician_is_the_same_404(
    api, world, db_session
) -> None:
    """R5.3: "una no asignada da el mismo `404` que una inexistente" — same status, same
    body, so the endpoint is not a probe for which incidents exist."""
    theirs = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await _assign_to(api, world, theirs.id, world.other_technician)
    headers = auth_header(api, world.technician)

    not_mine = await api.get(f"{INCIDENTS}/{theirs.id}", headers=headers)
    unknown = await api.get(f"{INCIDENTS}/{uuid.uuid4()}", headers=headers)

    assert not_mine.status_code == unknown.status_code == 404
    assert not_mine.json() == unknown.json()


async def test_a_technician_cannot_drive_an_incident_that_is_not_theirs(
    api, world, db_session
) -> None:
    theirs = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await _assign_to(api, world, theirs.id, world.other_technician)

    response = await api.post(
        f"{INCIDENTS}/{theirs.id}/accept", headers=auth_header(api, world.technician)
    )

    assert response.status_code == 404


async def test_the_assigned_technician_may_reject(api, world, db_session) -> None:
    """R1.6 — the assignee is exactly who this operation is for."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await _assign_to(api, world, incident.id, world.technician)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/reject", headers=auth_header(api, world.technician)
    )

    assert response.status_code == 200


async def test_a_manager_may_reject_to_unblock(api, world, db_session) -> None:
    """R1.6 — "y al `PROPERTY_MANAGER`", the same unblocking allowance the rest of the cycle
    gives (spec `maintenance` R6). A manager holds `EXECUTE_INCIDENTS` and is not narrowed to
    their own rows, because `restrict_to_technician_id` keys on the role."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await _assign_to(api, world, incident.id, world.technician)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/reject", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 200


async def test_rejecting_someone_elses_incident_is_the_same_404(
    api, world, db_session
) -> None:
    """R1.7 — "esa negativa SHALL ser indistinguible de «no existe»: el **mismo `404` con el
    mismo cuerpo**".

    Both halves asserted, and the body comparison is the one that matters: a distinguishable
    message would turn this route into a probe for which incidents exist and whose they are.

    **Three cases, and all three are executed** — somebody else's, nonexistent, and another
    tenant's — because R1.7 names all three as having to be identical. An earlier version of
    this test claimed the three in prose and built only two requests; the tenancy and QA panels
    both caught it, which is a fair reminder that a docstring is not coverage.

    What the third case does and does not prove is worth stating, because the shape recurs in
    this module: by the time it runs, the shared session is already bound to the caller's
    tenant, so its 404 is guaranteed by the session-level listener regardless of what this
    route does with `tenant_id`. It is here for the **body equality** — that the cross-tenant
    refusal is worded identically to the other two — which is the half R1.7 asks for and the
    half no session listener provides. The module's own scoping is pinned separately, and
    fallibly, by `test_the_api_scopes_the_lookup_to_the_callers_own_tenant`.
    """
    from app.properties.infrastructure.models import PropertyModel
    from app.tenants.infrastructure.models import TenantModel

    theirs = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await _assign_to(api, world, theirs.id, world.other_technician)
    headers = auth_header(api, world.technician)

    neighbour_tenant = TenantModel(name="TenantR", billing_email="r@example.com")
    db_session.add(neighbour_tenant)
    await db_session.flush()
    neighbour_property = PropertyModel(
        tenant_id=neighbour_tenant.id, name="Theirs", internal_code="THEIRSR"
    )
    db_session.add(neighbour_property)
    await db_session.flush()
    from tests.maintenance.conftest import World

    neighbour = World(
        neighbour_tenant,
        neighbour_property,
        await _user(db_session, neighbour_tenant, "TENANT_OWNER"),
        await _user(db_session, neighbour_tenant, "PROPERTY_MANAGER"),
        await _user(db_session, neighbour_tenant, "TECHNICIAN"),
        await _user(db_session, neighbour_tenant, "TECHNICIAN"),
    )
    elsewhere = await make_incident(
        db_session, neighbour, status=IncidentStatus.CLASSIFIED
    )

    not_mine = await api.post(f"{INCIDENTS}/{theirs.id}/reject", headers=headers)
    unknown = await api.post(f"{INCIDENTS}/{uuid.uuid4()}/reject", headers=headers)
    other_tenant = await api.post(f"{INCIDENTS}/{elsewhere.id}/reject", headers=headers)

    assert (
        not_mine.status_code
        == unknown.status_code
        == other_tenant.status_code
        == 404
    )
    assert not_mine.json() == unknown.json() == other_tenant.json()


async def test_the_api_scopes_the_lookup_to_the_callers_own_tenant(
    api, world, db_session, monkeypatch
) -> None:
    """R5.4, asserted on the API's **own** scoping rather than on the session-wide net.

    The 404 test below cannot fail, and it is worth saying why in full because the shape
    recurs. Its first authenticated call makes `get_authenticated_request` run
    `bind_session_to_tenant` (`app/auth/api/dependencies.py`), which installs a
    `with_loader_criteria(entity, entity.tenant_id == tenant_id)` on the shared session for
    **every** ORM `SELECT` for the rest of the test. From that moment the neighbour's row is
    invisible no matter what the router, the use case or the repository do with `tenant_id` —
    so a regression that dropped the argument between them would still 404, and still pass.
    That test pins `_scope_statement_to_tenant`; it does not pin this module.

    This one does, by watching the value that actually arrives at the repository. It is the
    assertion that goes red if the wiring regresses, which is what rule 1 of
    `sdd/steering/security.md` asks for when it demands tests that *demuestran* the isolation.
    """
    from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository

    seen: list[uuid.UUID] = []
    original = SqlAlchemyIncidentRepository.get

    async def _spy(self, tenant_id, incident_id):
        seen.append(tenant_id)
        return await original(self, tenant_id, incident_id)

    monkeypatch.setattr(SqlAlchemyIncidentRepository, "get", _spy)

    mine = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    response = await api.get(
        f"{INCIDENTS}/{mine.id}", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 200
    assert seen, "the request never reached SqlAlchemyIncidentRepository.get"
    assert seen == [world.tenant.id], (
        "the repository was asked for a tenant other than the caller's own: "
        f"{seen!r} != [{world.tenant.id!r}]"
    )


async def test_the_transition_routes_scope_the_lookup_to_the_callers_own_tenant(
    api, world, db_session, monkeypatch
) -> None:
    """The same assertion for the OTHER call site, which the test above does not reach.

    The detail route resolves through `GetIncidentUseCase.execute`; every mutating route —
    accept, start, wait-parts, resume, resolve, triage, assign, cancel — resolves through
    `_IncidentTransitionMixin._load_incident` instead. They are separate `incidents.get(...)`
    calls with separate wiring, so a spy on one proves nothing about the other. Found the
    hard way: a probe that broke `_load_incident`'s `tenant_id` left the whole suite green,
    including the spy above.
    """
    from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository

    seen: list[uuid.UUID] = []
    original = SqlAlchemyIncidentRepository.get

    async def _spy(self, tenant_id, incident_id):
        seen.append(tenant_id)
        return await original(self, tenant_id, incident_id)

    mine = await make_incident(db_session, world, status=IncidentStatus.ASSIGNED)
    mine.assigned_technician_id = world.technician.id
    await db_session.flush()

    monkeypatch.setattr(SqlAlchemyIncidentRepository, "get", _spy)

    response = await api.post(
        f"{INCIDENTS}/{mine.id}/accept", headers=auth_header(api, world.technician)
    )

    assert response.status_code == 200, response.text
    assert seen, "the request never reached SqlAlchemyIncidentRepository.get"
    assert set(seen) == {world.tenant.id}, (
        "a transition asked the repository for a tenant other than the caller's own: "
        f"{seen!r}"
    )


async def test_an_incident_of_another_tenant_is_a_404(api, world, db_session) -> None:
    """R5.4: "NEVER SHALL devolver una incidencia de otro tenant".

    Note what this proves and what it does not: by the time it asserts, the shared session is
    already bound to the caller's tenant, so the 404 is guaranteed by the session-level
    listener alone. It is kept because that net is itself worth pinning end-to-end through the
    real app; the module's own scoping is asserted in
    `test_the_api_scopes_the_lookup_to_the_callers_own_tenant` above, which can actually fail.
    """
    from app.properties.infrastructure.models import PropertyModel
    from app.tenants.infrastructure.models import TenantModel
    from tests.maintenance.conftest import World

    neighbour_tenant = TenantModel(name="TenantB", billing_email="b@example.com")
    db_session.add(neighbour_tenant)
    await db_session.flush()
    prop = PropertyModel(
        tenant_id=neighbour_tenant.id, name="Theirs", internal_code="THEIRS"
    )
    db_session.add(prop)
    await db_session.flush()
    neighbour = World(
        neighbour_tenant,
        prop,
        await _user(db_session, neighbour_tenant, "TENANT_OWNER"),
        await _user(db_session, neighbour_tenant, "PROPERTY_MANAGER"),
        await _user(db_session, neighbour_tenant, "TECHNICIAN"),
        await _user(db_session, neighbour_tenant, "TECHNICIAN"),
    )
    theirs = await make_incident(db_session, neighbour, status=IncidentStatus.CLASSIFIED)

    response = await api.get(
        f"{INCIDENTS}/{theirs.id}", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 404
