"""R2, R3, R4, R5 — `POST`/`GET /api/v1/incidents/{id}/messages`, end to end over ASGI.

The mirror of `tests/cleaning/test_messages_api.py`. What only this level can show: that
`EXECUTE_INCIDENTS` alone — with **no** `require_any` — really does let both a `TECHNICIAN`
and a `PROPERTY_MANAGER` write (design D3, unlike `cleaning`'s equivalent route), that a
`CLEANER` (who holds no incident permission at all) and a `TENANT_OWNER` (who holds
`READ_INCIDENTS` but neither `EXECUTE_` nor `MANAGE_INCIDENTS`) are refused where they should
be, that a `TECHNICIAN` reaching for another technician's thread gets the same `404` an
unknown id gets (never `403`), that the response body is the field allowlist of
`app/maintenance/api/schemas.py` and not a raw entity dump, and that the write really does
land a `NotificationLog` row for the right recipient. `tests/maintenance/test_incident_messages_use_case.py`
covers the notification branching, the pagination arithmetic and tenant isolation against
fakes; `tests/maintenance/test_repositories.py` covers tenant isolation against the real
database. This file wires the router.
"""

import uuid

import pytest
from sqlalchemy import select

from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
)
from app.maintenance.domain.entities import MAX_INCIDENT_MESSAGE_LENGTH
from app.maintenance.domain.exceptions import INCIDENT_NOT_FOUND_MESSAGE
from app.maintenance.infrastructure.models import IncidentMessageModel, IncidentModel
from app.notifications.domain.enums import NotificationType
from app.notifications.infrastructure.models import NotificationLogModel
from app.properties.domain.enums import PropertyOperationalState
from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel
from tests.maintenance.conftest import (  # noqa: F401
    api,
    auth_header,
    make_incident,
    world,
)

INCIDENTS = "/api/v1/incidents"

pytestmark = pytest.mark.asyncio


async def _assigned(db_session, world, technician=None) -> IncidentModel:
    """An incident assigned to a technician, `IN_PROGRESS` — the shape every test here starts
    from. The status is not what gates this route (unlike the photo routes'), but a real
    in-flight incident is what every one of these scenarios is really about."""
    incident = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    incident.assigned_technician_id = (technician or world.technician).id
    await db_session.flush()
    return incident


async def _unassigned(db_session, world) -> IncidentModel:
    """An `IN_PROGRESS` incident with no `assigned_technician_id` — R2.4's "including
    unassigned" and R4.3's "skip notification if unassigned" branch, which every other test
    in this file starts from `_assigned` and so never reaches."""
    return await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)


async def _foreign_tenant_incident(db_session) -> IncidentModel:
    """A second tenant's own incident, assigned to that tenant's own technician — the
    neighbour tenant an isolation test needs something real to fail to reach, never merely an
    id that never existed. Built inline rather than through `world`/`make_incident` because
    those are wired to the single tenant the `world` fixture already committed to the session
    (mirror of `tests/cleaning/test_messages_api.py`'s `tenant_b`/`cleaner_b`/`task_b`)."""
    tenant = TenantModel(name="TenantB", billing_email="b@example.com")
    db_session.add(tenant)
    await db_session.flush()
    prop = PropertyModel(
        tenant_id=tenant.id,
        name="Pajaritos 8",
        internal_code="PAJARITOS8",
        current_operational_state=PropertyOperationalState.VACANT_READY,
    )
    db_session.add(prop)
    await db_session.flush()
    technician = UserModel(
        tenant_id=tenant.id,
        name=f"Technician B {uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        password_hash="hash",
        role=UserRole.TECHNICIAN,
    )
    db_session.add(technician)
    await db_session.flush()
    incident = IncidentModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.GUEST,
        title="Fuga en el tenant vecino",
        description="No debería ser visible desde otro tenant.",
        category=IncidentCategory.OTHER,
        severity=IncidentSeverity.MEDIUM,
        status=IncidentStatus.IN_PROGRESS,
        assigned_technician_id=technician.id,
    )
    db_session.add(incident)
    await db_session.flush()
    return incident


async def _post_message(api, incident_id, user, content="Se necesita una pieza de recambio"):
    return await api.post(
        f"{INCIDENTS}/{incident_id}/messages",
        json={"content": content},
        headers=auth_header(api, user),
    )


async def _get_messages(api, incident_id, user, **params):
    return await api.get(
        f"{INCIDENTS}/{incident_id}/messages", params=params, headers=auth_header(api, user)
    )


async def _notifications_for(db_session, tenant_id, incident_id):
    rows = await db_session.execute(
        select(NotificationLogModel).where(
            NotificationLogModel.tenant_id == tenant_id,
            NotificationLogModel.notification_type == NotificationType.INCIDENT_MESSAGE.value,
            NotificationLogModel.related_id == incident_id,
        )
    )
    return list(rows.scalars())


# --- the happy path --------------------------------------------------------------------


async def test_the_assigned_technician_sends_a_message_and_notifies_every_active_manager(
    api, db_session, world
):
    incident = await _assigned(db_session, world)

    response = await _post_message(api, incident.id, world.technician)

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == "Se necesita una pieza de recambio"
    assert body["author_id"] == str(world.technician.id)
    assert body["author_role"] == "TECHNICIAN"
    assert uuid.UUID(body["id"])
    assert body["created_at"]

    row = await db_session.scalar(
        select(IncidentMessageModel).where(IncidentMessageModel.id == uuid.UUID(body["id"]))
    )
    assert row is not None
    assert row.incident_id == incident.id
    assert row.tenant_id == incident.tenant_id

    notifications = await _notifications_for(db_session, incident.tenant_id, incident.id)
    assert len(notifications) == 1
    assert notifications[0].recipient_user_id == world.manager.id


async def test_the_manager_sends_a_message_and_notifies_the_assigned_technician(
    api, db_session, world
):
    incident = await _assigned(db_session, world)

    response = await _post_message(
        api, incident.id, world.manager, content="¿Cuándo puedes pasar?"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["author_id"] == str(world.manager.id)
    assert body["author_role"] == "PROPERTY_MANAGER"

    notifications = await _notifications_for(db_session, incident.tenant_id, incident.id)
    assert len(notifications) == 1
    assert notifications[0].recipient_user_id == world.technician.id


async def test_the_manager_messages_an_unassigned_incident_and_notifies_nobody(
    api, db_session, world
):
    """R2.4 — `PROPERTY_MANAGER` is unrestricted "including unassigned"; R4.3 — no assigned
    technician means the notification is skipped, not failed. Every other `PROPERTY_MANAGER`
    test in this file starts from `_assigned`, so this HTTP layer never drove this branch
    before, even though `test_incident_messages_use_case.py` already covers it against fakes."""
    incident = await _unassigned(db_session, world)
    assert incident.assigned_technician_id is None

    response = await _post_message(
        api, incident.id, world.manager, content="Nota para cuando se asigne"
    )

    assert response.status_code == 201
    body = response.json()
    row = await db_session.scalar(
        select(IncidentMessageModel).where(IncidentMessageModel.id == uuid.UUID(body["id"]))
    )
    assert row is not None
    assert row.incident_id == incident.id

    notifications = await _notifications_for(db_session, incident.tenant_id, incident.id)
    assert notifications == []


async def test_the_response_body_is_the_allowlist_and_not_a_raw_dump(api, db_session, world):
    incident = await _assigned(db_session, world)

    response = await _post_message(api, incident.id, world.technician)

    assert set(response.json()) == {"id", "author_id", "content", "author_role", "created_at"}
    assert "tenant_id" not in response.text
    assert "incident_id" not in response.text


async def test_a_technician_reads_her_own_incident_thread(api, db_session, world):
    incident = await _assigned(db_session, world)
    await _post_message(api, incident.id, world.technician, content="Primero")
    await _post_message(api, incident.id, world.technician, content="Segundo")

    response = await _get_messages(api, incident.id, world.technician)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["content"] for item in body["data"]] == ["Primero", "Segundo"]
    assert body["page"] == 1
    assert body["per_page"] == 20
    assert body["total_pages"] == 1


async def test_a_manager_reads_the_thread_of_any_incident(api, db_session, world):
    incident = await _assigned(db_session, world)
    await _post_message(api, incident.id, world.technician)

    response = await _get_messages(api, incident.id, world.manager)

    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_pagination_bounds_and_paginates(api, db_session, world):
    incident = await _assigned(db_session, world)
    for i in range(3):
        await _post_message(api, incident.id, world.technician, content=f"mensaje {i}")

    response = await _get_messages(api, incident.id, world.technician, page=2, per_page=2)

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["per_page"] == 2
    assert body["total"] == 3
    assert body["total_pages"] == 2
    assert len(body["data"]) == 1


# --- the refusals ------------------------------------------------------------------------


async def test_content_over_the_maximum_length_is_422(api, db_session, world):
    incident = await _assigned(db_session, world)

    response = await _post_message(
        api, incident.id, world.technician, content="x" * (MAX_INCIDENT_MESSAGE_LENGTH + 1)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await db_session.scalar(select(IncidentMessageModel.id)) is None


async def test_content_at_exactly_the_maximum_length_is_accepted(api, db_session, world):
    incident = await _assigned(db_session, world)

    response = await _post_message(
        api, incident.id, world.technician, content="x" * MAX_INCIDENT_MESSAGE_LENGTH
    )

    assert response.status_code == 201
    assert len(response.json()["content"]) == MAX_INCIDENT_MESSAGE_LENGTH


async def test_empty_content_is_422(api, db_session, world):
    incident = await _assigned(db_session, world)

    response = await _post_message(api, incident.id, world.technician, content="   ")

    assert response.status_code == 422


async def test_an_unexpected_field_is_422(api, db_session, world):
    incident = await _assigned(db_session, world)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/messages",
        json={"content": "hola", "author_id": str(uuid.uuid4())},
        headers=auth_header(api, world.technician),
    )

    assert response.status_code == 422


async def test_a_cleaner_is_refused_on_both_routes(api, db_session, world):
    """`CLEANER` holds no incident permission at all (`ROLE_PERMISSIONS`) — a broken boiler is
    not part of doing a cleaning."""
    from app.auth.infrastructure.models import UserModel

    cleaner = UserModel(
        tenant_id=world.tenant.id,
        name="Limpiadora",
        email=f"cleaner-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x" * 60,
        role=UserRole.CLEANER,
    )
    db_session.add(cleaner)
    await db_session.flush()
    incident = await _assigned(db_session, world)

    post_response = await _post_message(api, incident.id, cleaner)
    get_response = await _get_messages(api, incident.id, cleaner)

    assert post_response.status_code == 403
    assert get_response.status_code == 403


async def test_the_owner_can_read_but_not_write(api, db_session, world):
    """`TENANT_OWNER` holds `READ_INCIDENTS` but neither `EXECUTE_` nor `MANAGE_INCIDENTS`
    (`auth/domain/policy.py`), so this is where the absence of a `require_any` on the write
    route actually bites for a role other than `CLEANER`."""
    incident = await _assigned(db_session, world)

    get_response = await _get_messages(api, incident.id, world.owner)
    post_response = await _post_message(api, incident.id, world.owner)

    assert get_response.status_code == 200
    assert post_response.status_code == 403


async def test_an_anonymous_request_is_401(api, db_session, world):
    incident = await _assigned(db_session, world)

    post_response = await api.post(f"{INCIDENTS}/{incident.id}/messages", json={"content": "hola"})
    get_response = await api.get(f"{INCIDENTS}/{incident.id}/messages")

    assert post_response.status_code == 401
    assert get_response.status_code == 401


# --- row-level scoping (R2.3) --------------------------------------------------------------


async def test_messaging_an_unknown_incident_is_404(api, world):
    response = await _post_message(api, uuid.uuid4(), world.technician)

    assert response.status_code == 404
    assert response.json()["error"]["message"] == INCIDENT_NOT_FOUND_MESSAGE


async def test_reading_an_unknown_incident_is_404(api, world):
    response = await _get_messages(api, uuid.uuid4(), world.technician)

    assert response.status_code == 404


async def test_a_technician_cannot_message_an_incident_that_is_not_hers(api, db_session, world):
    incident = await _assigned(db_session, world)

    response = await _post_message(api, incident.id, world.other_technician)
    unknown = await _post_message(api, uuid.uuid4(), world.other_technician)

    assert response.status_code == 404
    assert response.content == unknown.content


async def test_a_technician_cannot_read_an_incident_that_is_not_hers(api, db_session, world):
    incident = await _assigned(db_session, world)

    response = await _get_messages(api, incident.id, world.other_technician)
    unknown = await _get_messages(api, uuid.uuid4(), world.other_technician)

    assert response.status_code == 404
    assert response.content == unknown.content


# --- isolation (R3.2) ----------------------------------------------------------------------


async def test_messaging_another_tenants_incident_is_the_same_404_as_an_unknown_id(
    api, db_session, world
):
    foreign = await _foreign_tenant_incident(db_session)

    response = await _post_message(api, foreign.id, world.technician)
    unknown = await _post_message(api, uuid.uuid4(), world.technician)

    assert response.status_code == unknown.status_code == 404
    assert response.content == unknown.content
    assert response.json()["error"]["message"] == INCIDENT_NOT_FOUND_MESSAGE


async def test_reading_another_tenants_incident_is_the_same_404_as_an_unknown_id(
    api, db_session, world
):
    foreign = await _foreign_tenant_incident(db_session)

    response = await _get_messages(api, foreign.id, world.technician)
    unknown = await _get_messages(api, uuid.uuid4(), world.technician)

    assert response.status_code == unknown.status_code == 404
    assert response.content == unknown.content
