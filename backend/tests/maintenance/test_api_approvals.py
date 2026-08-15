"""`POST /owner-approvals/{id}/respond` over HTTP (R2.4, R2.5, R2.6; design D14)."""

import uuid

import pytest

from app.maintenance.domain.enums import (
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)
from tests.maintenance.conftest import (  # noqa: F401
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


async def test_there_is_no_listing_route(api, world) -> None:
    """D13: no `READ_OWNER_APPROVALS` and no listing. The dashboard already exposes the
    pending approvals of a property, and the notification of R2.3 is what tells the owner."""
    response = await api.get(APPROVALS, headers=auth_header(api, world.owner))

    assert response.status_code in (404, 405)
