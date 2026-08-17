"""The incident endpoints over HTTP (R5.1, R5.3, R5.4; design D14).

Through the real app, not the use cases: what these add over `test_use_cases.py` is the
half that only exists at this layer — `require(...)`, the PRD §23 error envelope, the
response schema's field list, and the pagination bounds.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentStatus,
    OwnerApprovalRelatedType,
)
from app.maintenance.infrastructure.models import IncidentModel, OwnerApprovalModel
from tests.maintenance.conftest import (  # noqa: F401
    NOW,
    api,
    auth_header,
    flow,
    make_approval,
    make_incident,
    world,
)

pytestmark = pytest.mark.asyncio

INCIDENTS = "/api/v1/incidents"


async def _assigned(api, world, db_session) -> IncidentModel:
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    response = await api.post(
        f"{INCIDENTS}/{incident.id}/assign",
        json={"technician_id": str(world.technician.id)},
        headers=auth_header(api, world.manager),
    )
    assert response.status_code == 200
    return incident


# --- Reading (R5.1) ---------------------------------------------------------------------


async def test_the_listing_is_paginated_and_shaped(api, world, db_session) -> None:
    for _ in range(3):
        await make_incident(db_session, world)

    response = await api.get(
        INCIDENTS, params={"page": 1, "per_page": 2}, headers=auth_header(api, world.manager)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["per_page"] == 2
    assert len(body["items"]) == 2


async def test_the_response_never_carries_the_reporter_or_the_raw_verdict(
    api, world, db_session
) -> None:
    """What the security panel of section 5 asked this section to prove, on the serialised
    payload rather than on the entity: `reported_by_guest_token`, `reported_by_user_id` and
    `ai_classification` are not fields of the response at all."""
    incident = await make_incident(db_session, world)
    stored = await db_session.get(IncidentModel, incident.id)
    stored.reported_by_guest_token = "digest-of-a-portal-token"
    stored.ai_classification = {"category": "WATER", "confidence": "0.9"}
    await db_session.flush()

    listing = await api.get(INCIDENTS, headers=auth_header(api, world.manager))
    detail = await api.get(
        f"{INCIDENTS}/{incident.id}", headers=auth_header(api, world.manager)
    )

    for payload in (listing.json()["items"][0], detail.json()):
        assert "reported_by_guest_token" not in payload
        assert "reported_by_user_id" not in payload
        assert "ai_classification" not in payload
        # And what a technician does need is there.
        assert payload["description"]


async def test_an_unknown_incident_is_a_404_in_the_prd_envelope(api, world) -> None:
    response = await api.get(
        f"{INCIDENTS}/{uuid.uuid4()}", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("params", "reason"),
    [
        ({"page": 0}, "page below the floor"),
        ({"per_page": 0}, "per_page below the floor"),
        ({"per_page": 101}, "per_page above the ceiling"),
        ({"page": 10**9}, "page above the ceiling"),
    ],
)
async def test_the_pagination_bounds_are_refused_before_the_database(
    api, world, params: dict, reason: str
) -> None:
    """The port refuses a non-positive page; the **ceiling** belongs here, or one request
    pulls a tenant's whole incident table with its descriptions in it."""
    response = await api.get(
        INCIDENTS, params=params, headers=auth_header(api, world.manager)
    )

    assert response.status_code == 422, reason


# --- The flow over HTTP (R1, R3, R4) ----------------------------------------------------


async def test_the_happy_path_of_every_route(api, world, db_session) -> None:
    incident = await make_incident(
        db_session, world, description="Hay una fuga de agua en el baño."
    )
    manager = auth_header(api, world.manager)
    technician = auth_header(api, world.technician)

    classified = await api.post(f"{INCIDENTS}/{incident.id}/classify", headers=manager)
    assert classified.status_code == 200
    assert classified.json()["status"] == IncidentStatus.CLASSIFIED.value

    triaged = await api.patch(
        f"{INCIDENTS}/{incident.id}",
        json={"severity": IncidentSeverity.HIGH.value, "estimated_cost": "40.00"},
        headers=manager,
    )
    assert triaged.status_code == 200
    assert triaged.json()["estimated_cost"] == "40.00"

    assigned = await api.post(
        f"{INCIDENTS}/{incident.id}/assign",
        json={"technician_id": str(world.technician.id)},
        headers=manager,
    )
    assert assigned.json()["status"] == IncidentStatus.ASSIGNED.value

    for route, expected in (
        ("accept", IncidentStatus.ACCEPTED),
        ("start", IncidentStatus.IN_PROGRESS),
        ("wait-parts", IncidentStatus.WAITING_EXTERNAL_PARTS),
        ("resume", IncidentStatus.IN_PROGRESS),
    ):
        step = await api.post(f"{INCIDENTS}/{incident.id}/{route}", headers=technician)
        assert step.status_code == 200, route
        assert step.json()["status"] == expected.value

    resolved = await api.post(
        f"{INCIDENTS}/{incident.id}/resolve",
        json={"final_cost": "60.00"},
        headers=technician,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == IncidentStatus.RESOLVED.value
    assert resolved.json()["resolved_at"] is not None


async def test_cancelling_is_its_own_route(api, world, db_session) -> None:
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/cancel", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 200
    assert response.json()["status"] == IncidentStatus.CANCELLED.value


async def test_a_step_out_of_order_is_a_409(api, world, db_session) -> None:
    """R4.4 in the PRD §23 envelope."""
    incident = await _assigned(api, world, db_session)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/start", headers=auth_header(api, world.technician)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_a_closed_incident_is_a_409(api, world, db_session) -> None:
    incident = await make_incident(db_session, world, status=IncidentStatus.RESOLVED)

    response = await api.patch(
        f"{INCIDENTS}/{incident.id}",
        json={"severity": IncidentSeverity.LOW.value},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 409


async def test_an_incident_awaiting_the_owner_blocks_with_a_409(
    api, world, db_session
) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/assign",
        json={"technician_id": str(world.technician.id)},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 409


async def test_an_invalid_assignee_is_a_422(api, world, db_session) -> None:
    """R3.4 — the manager is not a technician."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/assign",
        json={"technician_id": str(world.manager.id)},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_resolving_without_a_cost_is_a_422(api, world, db_session) -> None:
    """R4.2: "SHALL exigir `final_cost`", which at this layer is the schema's job."""
    incident = await _assigned(api, world, db_session)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/resolve",
        json={},
        headers=auth_header(api, world.technician),
    )

    assert response.status_code == 422


async def test_a_body_with_an_unknown_field_is_refused(api, world, db_session) -> None:
    """`extra="forbid"` — a `tenant_id` in a body must never reach a use case."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    response = await api.patch(
        f"{INCIDENTS}/{incident.id}",
        json={"tenant_id": str(uuid.uuid4())},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422


async def test_the_second_gate_answers_with_the_parked_incident(
    api, world, db_session
) -> None:
    """R4.3 over HTTP: a cost past the threshold does not resolve, and the caller can see
    that from the body it gets back."""
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)
    await api.post(f"{INCIDENTS}/{incident.id}/start", headers=technician)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/resolve",
        json={"final_cost": "500.00"},
        headers=technician,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == IncidentStatus.AWAITING_OWNER_APPROVAL.value
    assert body["final_cost"] == "500.00"
    assert body["resolved_at"] is None

    approvals = await db_session.execute(select(OwnerApprovalModel))
    approval = approvals.scalars().one()
    assert approval.related_type is OwnerApprovalRelatedType.MAINTENANCE_COST


# --- There is no creation route (D14) ---------------------------------------------------


async def test_there_is_no_post_incidents(api, world) -> None:
    """The most visible absence of D14's table, asserted so it stays a decision.

    Every source that creates an incident has a declared owner: the guest portal already
    does, `messaging-ai` will bring the conversational intent, and `LOCK_ALERT` has no
    import surface to hang off.
    """
    response = await api.post(
        INCIDENTS, json={"title": "x", "description": "y"}, headers=auth_header(api, world.manager)
    )

    assert response.status_code == 405
