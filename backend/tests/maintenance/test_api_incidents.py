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
        ("en-route", IncidentStatus.IN_PROGRESS),
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


async def test_the_old_start_route_no_longer_exists(api, world, db_session) -> None:
    """R2.3 — "se renombra, no se duplica", proved against the app's own route table.

    A `404` and not a `405`: FastAPI answers `405` when the path matches and the method does
    not, so a `404` is what says the path itself is gone. There was no consumer to protect
    (measured: nothing under `frontend/`, no CLI, no scheduler), which is why the rename does
    not leave an alias behind.
    """
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)

    response = await api.post(f"{INCIDENTS}/{incident.id}/start", headers=technician)

    assert response.status_code == 404


# --- The refusal over HTTP (R1.6, R1.8) -------------------------------------------------


@pytest.mark.parametrize("origin", ["assigned", "accepted"])
async def test_rejecting_over_http_from_both_origins(
    api, world, db_session, origin: str
) -> None:
    """R1.1, R1.2, R1.6 — and the body it answers with shows the caller the three cleared
    fields, which is what a client needs to redraw the screen."""
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    if origin == "accepted":
        assert (
            await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)
        ).status_code == 200

    response = await api.post(f"{INCIDENTS}/{incident.id}/reject", headers=technician)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == IncidentStatus.CLASSIFIED.value
    assert body["assigned_technician_id"] is None
    assert body["eta_at"] is None


async def test_rejecting_out_of_order_is_a_409(api, world, db_session) -> None:
    """R1.8 in the PRD §23 envelope — `CLASSIFIED` is not an origin of `reject`."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/reject", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_rejecting_a_closed_incident_is_a_409(api, world, db_session) -> None:
    """R1.8's first branch: a terminal incident admits no move at all."""
    incident = await make_incident(db_session, world, status=IncidentStatus.RESOLVED)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/reject", headers=auth_header(api, world.manager)
    )

    assert response.status_code == 409


# --- The ETA over HTTP (R3.2, R3.4, R3.6) -----------------------------------------------


@pytest.mark.parametrize("route", ["accept", "en-route"])
async def test_the_two_routes_accept_an_eta(api, world, db_session, route: str) -> None:
    """R3.2 — and only these two take a body at all."""
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    if route == "en-route":
        await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)
    eta = (NOW + timedelta(days=400)).isoformat()

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/{route}", json={"eta_at": eta}, headers=technician
    )

    assert response.status_code == 200, response.text
    assert response.json()["eta_at"] is not None


@pytest.mark.parametrize("route", ["accept", "en-route"])
async def test_the_two_routes_still_work_with_no_body_at_all(
    api, world, db_session, route: str
) -> None:
    """D6 — the parameter is `IncidentEtaRequest | None = None`, so the pre-change call shape
    is untouched. Worth its own test: making the body required would be a silent break of
    every existing caller."""
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    if route == "en-route":
        await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)

    response = await api.post(f"{INCIDENTS}/{incident.id}/{route}", headers=technician)

    assert response.status_code == 200, response.text
    assert response.json()["eta_at"] is None


@pytest.mark.parametrize("route", ["accept", "en-route"])
async def test_an_eta_in_the_past_is_a_422(api, world, db_session, route: str) -> None:
    """R3.4 over HTTP — `MaintenanceValidationError` maps to `422 VALIDATION_ERROR`."""
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    if route == "en-route":
        await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/{route}",
        json={"eta_at": "2020-01-01T10:00:00+00:00"},
        headers=technician,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("route", ["accept", "en-route"])
async def test_an_eta_without_a_timezone_is_a_422(
    api, world, db_session, route: str
) -> None:
    """D6 — without the explicit `tzinfo` check this is a `TypeError` and an undeclared 500."""
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    if route == "en-route":
        await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/{route}",
        json={"eta_at": "2099-01-01T10:00:00"},
        headers=technician,
    )

    assert response.status_code == 422


@pytest.mark.parametrize("route", ["accept", "en-route"])
async def test_an_unknown_field_in_the_eta_body_is_a_422(
    api, world, db_session, route: str
) -> None:
    """R3.6 — `extra="forbid"` is what makes that a `422` and not a convention."""
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    if route == "en-route":
        await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/{route}",
        json={"eta_at": None, "assigned_technician_id": str(uuid.uuid4())},
        headers=technician,
    )

    assert response.status_code == 422


# --- The materials over HTTP (R4.1, R4.2) -----------------------------------------------


async def test_resolving_accepts_and_returns_the_materials(
    api, world, db_session
) -> None:
    """R4.1, R4.2 — and the value comes back on the response, stripped."""
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)
    await api.post(f"{INCIDENTS}/{incident.id}/en-route", headers=technician)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/resolve",
        json={"final_cost": "60.00", "materials": "  Dos codos de 22 mm  "},
        headers=technician,
    )

    assert response.status_code == 200, response.text
    assert response.json()["materials"] == "Dos codos de 22 mm"


async def test_an_empty_materials_string_is_a_422(api, world, db_session) -> None:
    """D7 — "sin materiales" is said by omitting the field, not by sending `""`.

    `str_strip_whitespace=True` with `min_length=1` is what makes a whitespace-only value a
    `422` too, which is the case a bare `min_length` would let through.
    """
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)
    await api.post(f"{INCIDENTS}/{incident.id}/en-route", headers=technician)

    for value in ("", "   "):
        response = await api.post(
            f"{INCIDENTS}/{incident.id}/resolve",
            json={"final_cost": "60.00", "materials": value},
            headers=technician,
        )
        assert response.status_code == 422, value


async def test_over_long_materials_is_a_422(api, world, db_session) -> None:
    """R4.1 — bounded in the request schema as well as in the DDL, so this is a `422` rather
    than a driver error that aborts the transaction."""
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)
    await api.post(f"{INCIDENTS}/{incident.id}/accept", headers=technician)
    await api.post(f"{INCIDENTS}/{incident.id}/en-route", headers=technician)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/resolve",
        json={"final_cost": "60.00", "materials": "x" * 2001},
        headers=technician,
    )

    assert response.status_code == 422


async def test_materials_is_refused_on_the_other_bodies(api, world, db_session) -> None:
    """R4.2 — "NEVER SHALL aceptarlo en ninguna otra ruta", made a `422` by `extra="forbid"`."""
    incident = await _assigned(api, world, db_session)
    technician = auth_header(api, world.technician)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/accept",
        json={"materials": "Dos codos"},
        headers=technician,
    )

    assert response.status_code == 422


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
        f"{INCIDENTS}/{incident.id}/en-route", headers=auth_header(api, world.technician)
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
    await api.post(f"{INCIDENTS}/{incident.id}/en-route", headers=technician)

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


# --- The optional note on `assign` (R3.2, R3.3) ------------------------------------------


@pytest.mark.parametrize(
    ("body_extra", "expected"),
    [
        ({}, None),
        ({"assignment_note": None}, None),
        ({"assignment_note": "Portal code 4821."}, "Portal code 4821."),
    ],
)
async def test_assign_accepts_the_note_as_an_optional_field(
    api, world, db_session, body_extra: dict, expected: str | None
) -> None:
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/assign",
        json={"technician_id": str(world.technician.id), **body_extra},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 200
    stored = await db_session.get(IncidentModel, incident.id)
    await db_session.refresh(stored)
    assert stored.assignment_note == expected


async def test_a_note_over_the_bound_is_a_422(api, world, db_session) -> None:
    """The pydantic half of D6's two-sided bound. The DDL is the other half
    (`tests/maintenance/test_models.py`); without this the driver would raise instead of the
    PRD §23 envelope answering."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/assign",
        json={"technician_id": str(world.technician.id), "assignment_note": "x" * 2001},
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422


async def test_the_assign_body_still_forbids_an_unknown_field(api, world, db_session) -> None:
    """R3.2 — `extra="forbid"` survives the new field, so a `tenant_id` is still refused."""
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    response = await api.post(
        f"{INCIDENTS}/{incident.id}/assign",
        json={
            "technician_id": str(world.technician.id),
            "tenant_id": str(uuid.uuid4()),
        },
        headers=auth_header(api, world.manager),
    )

    assert response.status_code == 422


async def test_the_incident_contract_does_not_gain_the_note(api, world, db_session) -> None:
    """R3.3 of `tech-incident-context` — the note lives on the projection and nowhere else.

    Asserted as the **exact** key set of both bodies, so a `from_attributes` slip or a field
    appended to `IncidentResponse` reddens here rather than being noticed in a client.

    It did exactly that when `tech-cycle-completion` added `eta_at` and `materials` (its R3.1,
    R4.1, design D8). Both are deliberate additions to this contract and both appear in the
    **listing** as well as the detail, because one schema serves both. What the test is
    guarding stays untouched: `assignment_note` is still absent, and so is everything that
    identifies the reporter (`reported_by_guest_token`, `reported_by_user_id`) and the raw
    classifier verdict (`ai_classification`).
    """
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await api.post(
        f"{INCIDENTS}/{incident.id}/assign",
        json={
            "technician_id": str(world.technician.id),
            "assignment_note": "Portal code 4821.",
        },
        headers=auth_header(api, world.manager),
    )
    manager = auth_header(api, world.manager)

    detail = await api.get(f"{INCIDENTS}/{incident.id}", headers=manager)
    listing = await api.get(INCIDENTS, headers=manager)

    expected = {
        "id",
        "property_id",
        "reservation_id",
        "source",
        "category",
        "severity",
        "status",
        "title",
        "description",
        "ai_summary",
        "assigned_technician_id",
        "owner_approval_required",
        "estimated_cost",
        "approved_cost",
        "final_cost",
        "resolved_at",
        "created_at",
        "updated_at",
        # `tech-cycle-completion` R3.1/R4.1 — added on purpose, listing included (D8).
        "eta_at",
        "materials",
    }
    assert set(detail.json()) == expected
    assert set(listing.json()["items"][0]) == expected
    # The point of the test, restated so a future widening of `expected` cannot quietly
    # swallow it: the note and the reporter's identity are still out.
    for absent in (
        "assignment_note",
        "reported_by_guest_token",
        "reported_by_user_id",
        "ai_classification",
    ):
        assert absent not in detail.json()
        assert absent not in listing.json()["items"][0]


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
