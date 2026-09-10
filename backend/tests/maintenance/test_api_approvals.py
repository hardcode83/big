"""`POST /owner-approvals/{id}/respond` and `GET /owner-approvals` over HTTP (R2.4, R2.5,
R2.6, R1; design D14, `approvals-web` D1-D5)."""

import uuid

import pytest

from app.maintenance.domain.enums import (
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)
from tests.maintenance.conftest import (  # noqa: F401
    _user,
    api,
    auth_header,
    make_approval,
    make_incident,
    world,
)

pytestmark = pytest.mark.asyncio

APPROVALS = "/api/v1/owner-approvals"


async def test_approving_returns_the_incident_to_the_flow(api, world, db_session) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)

    response = await api.post(
        f"{APPROVALS}/{approval.id}/respond",
        json={"status": OwnerApprovalStatus.APPROVED.value, "response_notes": "Adelante."},
        headers=auth_header(api, world.owner),
    )

    assert response.status_code == 200
    body = response.json()
    # The **incident** comes back, not the approval: what the caller does next depends on
    # where the incident ended up.
    assert body["id"] == str(incident.id)
    assert body["status"] == IncidentStatus.CLASSIFIED.value
    assert body["approved_cost"] == "450.00"


async def test_approving_a_real_cost_returns_it_to_in_progress(
    api, world, db_session
) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(
        db_session,
        world,
        incident.id,
        related_type=OwnerApprovalRelatedType.MAINTENANCE_COST,
    )

    response = await api.post(
        f"{APPROVALS}/{approval.id}/respond",
        json={"status": OwnerApprovalStatus.APPROVED.value},
        headers=auth_header(api, world.owner),
    )

    assert response.json()["status"] == IncidentStatus.IN_PROGRESS.value
    assert response.json()["resolved_at"] is None


async def test_rejecting_cancels_the_incident(api, world, db_session) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)

    response = await api.post(
        f"{APPROVALS}/{approval.id}/respond",
        json={"status": OwnerApprovalStatus.REJECTED.value, "response_notes": "Muy caro."},
        headers=auth_header(api, world.owner),
    )

    assert response.json()["status"] == IncidentStatus.CANCELLED.value


async def test_answering_twice_is_a_409(api, world, db_session) -> None:
    """R2.6, and over HTTP the second call is a separate request against a stored row."""
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)
    payload = {"status": OwnerApprovalStatus.APPROVED.value}

    first = await api.post(
        f"{APPROVALS}/{approval.id}/respond",
        json=payload,
        headers=auth_header(api, world.owner),
    )
    second = await api.post(
        f"{APPROVALS}/{approval.id}/respond",
        json=payload,
        headers=auth_header(api, world.owner),
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"


async def test_an_unknown_approval_is_a_404(api, world) -> None:
    response = await api.post(
        f"{APPROVALS}/{uuid.uuid4()}/respond",
        json={"status": OwnerApprovalStatus.APPROVED.value},
        headers=auth_header(api, world.owner),
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "answer", [OwnerApprovalStatus.PENDING.value, OwnerApprovalStatus.EXPIRED.value]
)
async def test_only_approved_or_rejected_is_an_answer(
    api, world, db_session, answer: str
) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)

    response = await api.post(
        f"{APPROVALS}/{approval.id}/respond",
        json={"status": answer},
        headers=auth_header(api, world.owner),
    )

    assert response.status_code == 422


async def test_the_notes_are_bounded(api, world, db_session) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)

    response = await api.post(
        f"{APPROVALS}/{approval.id}/respond",
        json={
            "status": OwnerApprovalStatus.APPROVED.value,
            "response_notes": "x" * 2001,
        },
        headers=auth_header(api, world.owner),
    )

    assert response.status_code == 422


async def test_the_owner_lists_pending_approvals(api, world, db_session) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    await make_approval(db_session, world, incident.id)

    response = await api.get(APPROVALS, headers=auth_header(api, world.owner))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


async def test_the_manager_also_lists_pending_approvals(api, world, db_session) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    await make_approval(db_session, world, incident.id)

    response = await api.get(APPROVALS, headers=auth_header(api, world.manager))

    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.parametrize("role", ["TECHNICIAN", "CLEANER"])
async def test_a_technician_or_cleaner_is_refused(
    api, world, db_session, role: str
) -> None:
    """R1.4 — the measured false reuse of `READ_INCIDENTS` must NOT grant this: a
    `TECHNICIAN` holds `READ_INCIDENTS` and must still be refused here."""
    user = world.technician if role == "TECHNICIAN" else await _user(
        db_session, world.tenant, "CLEANER"
    )

    response = await api.get(APPROVALS, headers=auth_header(api, user))

    assert response.status_code == 403


async def test_default_status_is_pending_oldest_first(api, world, db_session) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    pending = await make_approval(db_session, world, incident.id)
    answered_incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    answered = await make_approval(db_session, world, answered_incident.id)
    answered.status = OwnerApprovalStatus.APPROVED
    await db_session.flush()

    response = await api.get(APPROVALS, headers=auth_header(api, world.owner))

    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(pending.id)]
    assert body["total"] == 1


async def test_status_filter_round_trips(api, world, db_session) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)
    approval.status = OwnerApprovalStatus.APPROVED
    await db_session.flush()

    response = await api.get(
        APPROVALS,
        params={"status": OwnerApprovalStatus.APPROVED.value},
        headers=auth_header(api, world.owner),
    )

    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(approval.id)]
    assert all(item["status"] == "APPROVED" for item in body["items"])


async def test_the_response_shape_carries_incident_and_property_never_a_raw_row(
    api, world, db_session
) -> None:
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    approval = await make_approval(db_session, world, incident.id)

    response = await api.get(APPROVALS, headers=auth_header(api, world.owner))

    item = response.json()["items"][0]
    assert item["id"] == str(approval.id)
    assert item["related_type"] == OwnerApprovalRelatedType.INCIDENT.value
    assert item["status"] == OwnerApprovalStatus.PENDING.value
    assert item["amount"] == "450.00"
    assert item["currency"] == "EUR"
    assert item["incident"]["id"] == str(incident.id)
    assert item["incident"]["title"] == incident.title
    assert item["incident"]["category"] == incident.category.value
    assert item["incident"]["severity"] == incident.severity.value
    assert item["property"]["id"] == str(world.property.id)
    assert item["property"]["name"] == world.property.name
    assert item["property"]["internal_code"] == world.property.internal_code
    # No raw row: `reason`/`response_notes` are not fields of this projection (D2).
    assert "reason" not in item
    assert "response_notes" not in item


async def test_another_tenants_approvals_never_appear(api, world, db_session) -> None:
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
    elsewhere_incident = await make_incident(
        db_session, neighbour, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    await make_approval(db_session, neighbour, elsewhere_incident.id)
    # This tenant has a pending approval of its own, so an empty page would not prove
    # isolation — it might just mean the query is broken outright.
    mine_incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    mine = await make_approval(db_session, world, mine_incident.id)

    response = await api.get(APPROVALS, headers=auth_header(api, world.owner))

    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(mine.id)]
    assert body["total"] == 1
