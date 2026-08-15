"""Who may reach the twelve routes, and what they see when they do (R5.2, R5.3, R5.4).

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
    ("POST", INCIDENTS + "/{incident_id}/classify"),
    ("PATCH", INCIDENTS + "/{incident_id}"),
    ("POST", INCIDENTS + "/{incident_id}/assign"),
    ("POST", INCIDENTS + "/{incident_id}/accept"),
    ("POST", INCIDENTS + "/{incident_id}/start"),
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
    checked per route — the role holds none of the four permissions (D13)."""
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


async def test_an_incident_of_another_tenant_is_a_404(api, world, db_session) -> None:
    """R5.4: "NEVER SHALL devolver una incidencia de otro tenant", through the marked
    session the API actually uses."""
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
