"""The access-record endpoints (R2, R3).

The load-bearing assertions here are the two the design turns on: **the plaintext code never
comes back** on any path, and a cross-tenant reference is a `404` whose body is byte-identical
to the one for an id that does not exist (R3.3).
"""

import pytest
from sqlalchemy import select

from app.access.domain.enums import AccessRecordStatus
from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import UserRole
from app.timeline.infrastructure.models import TimelineEventModel
from tests.access.conftest import (
    auth_header,
    insert_access_record,
    insert_reservation,
)

RECORDS = "/api/v1/access-records"
CODE = "481523"


@pytest.mark.asyncio
async def test_registering_a_code_returns_only_the_mask(
    api, db_session, tenant_a, property_a, users_by_role_a
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    record = await insert_access_record(
        db_session, tenant_a, property_a, reservation=reservation
    )

    response = await api.post(
        f"{RECORDS}/{record.id}/manual-code",
        json={"code": CODE, "notes": "left with the neighbour"},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "MANUAL_ADDED"
    assert body["code_masked"] == "****23"
    # Design D9, over the whole response rather than a named field.
    assert CODE not in response.text
    assert "code" not in body


@pytest.mark.asyncio
async def test_the_full_operator_path_ends_in_delivered(
    api, db_session, tenant_a, property_a, users_by_role_a
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    record = await insert_access_record(
        db_session, tenant_a, property_a, reservation=reservation
    )
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    await api.post(f"{RECORDS}/{record.id}/manual-code", json={"code": CODE}, headers=header)
    delivered = await api.post(f"{RECORDS}/{record.id}/delivered", headers=header)

    assert delivered.status_code == 200
    assert delivered.json()["status"] == "DELIVERED"


@pytest.mark.asyncio
async def test_marking_external_needs_no_code(
    api, db_session, tenant_a, property_a, users_by_role_a
) -> None:
    record = await insert_access_record(db_session, tenant_a, property_a)

    response = await api.post(
        f"{RECORDS}/{record.id}/external",
        json={"notes": "GrinPass imported it"},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CREATED_EXTERNAL"
    assert response.json()["code_masked"] is None


@pytest.mark.asyncio
async def test_an_invalid_transition_is_a_409(
    api, db_session, tenant_a, property_a, users_by_role_a
) -> None:
    """R2.5 — confirming delivery of a code nobody registered has no basis."""
    record = await insert_access_record(db_session, tenant_a, property_a)

    response = await api.post(
        f"{RECORDS}/{record.id}/delivered",
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload", "origin"),
    [
        ("manual-code", {"code": CODE}, AccessRecordStatus.DELIVERED),
        ("external", {}, AccessRecordStatus.MANUAL_ADDED),
        ("delivered", None, AccessRecordStatus.PENDING),
    ],
)
async def test_a_409_leaves_no_trace_in_the_database(
    api, db_session, tenant_a, property_a, users_by_role_a, path, payload, origin
) -> None:
    """R2.5: "rechazarla con `409` **y no escribir ningún evento**".

    Until the feature-scale QA panel said so, that clause was proven only by reading the
    control flow — the entity raises before `_persist` is reached — and no test looked at the
    database afterwards. A refactor that called a base-class `_persist` speculatively would
    have shipped. One case per transition endpoint, since only one of the three had a 409
    test at all.
    """
    record = await insert_access_record(db_session, tenant_a, property_a, status=origin)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    url = f"{RECORDS}/{record.id}/{path}"

    response = (
        await api.post(url, headers=header)
        if payload is None
        else await api.post(url, json=payload, headers=header)
    )

    assert response.status_code == 409
    await db_session.refresh(record)
    assert record.status is origin
    events = await db_session.execute(
        select(TimelineEventModel).where(TimelineEventModel.tenant_id == tenant_a.id)
    )
    audit = await db_session.execute(
        select(AuditLogModel).where(AuditLogModel.tenant_id == tenant_a.id)
    )
    assert list(events.scalars()) == []
    assert list(audit.scalars()) == []


@pytest.mark.asyncio
async def test_an_empty_code_is_refused(
    api, db_session, tenant_a, property_a, users_by_role_a
) -> None:
    record = await insert_access_record(db_session, tenant_a, property_a)

    response = await api.post(
        f"{RECORDS}/{record.id}/manual-code",
        json={"code": "   "},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 422


# --- isolation and RBAC (R3.2, R3.3, R3.4) ---------------------------------------


@pytest.mark.asyncio
async def test_a_neighbours_record_is_the_same_404_as_a_missing_one(
    api, db_session, tenant_a, tenant_b, property_b, users_by_role_a
) -> None:
    """R3.3 — **byte-identical**, not merely both 404: a different body would tell the caller
    the id exists somewhere, which is the existence oracle the rule forbids."""
    import uuid

    theirs = await insert_access_record(db_session, tenant_b, property_b)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    cross_tenant = await api.get(f"{RECORDS}/{theirs.id}", headers=header)
    nonexistent = await api.get(f"{RECORDS}/{uuid.uuid4()}", headers=header)

    assert cross_tenant.status_code == nonexistent.status_code == 404
    assert cross_tenant.json() == nonexistent.json()


@pytest.mark.asyncio
async def test_a_write_to_a_neighbours_record_is_also_a_404(
    api, db_session, tenant_a, tenant_b, property_b, users_by_role_a
) -> None:
    theirs = await insert_access_record(db_session, tenant_b, property_b)

    response = await api.post(
        f"{RECORDS}/{theirs.id}/manual-code",
        json={"code": CODE},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_listing_shows_only_this_tenants_records(
    api, db_session, tenant_a, tenant_b, property_a, property_b, users_by_role_a
) -> None:
    mine = await insert_access_record(db_session, tenant_a, property_a)
    await insert_access_record(db_session, tenant_b, property_b)

    response = await api.get(
        RECORDS, headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [str(mine.id)]


@pytest.mark.asyncio
async def test_the_owner_reads_but_cannot_operate(
    api, db_session, tenant_a, property_a, users_by_role_a
) -> None:
    """R3.4 — PRD §6 gives the owner visibility and the manager the operation."""
    record = await insert_access_record(db_session, tenant_a, property_a)
    header = auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])

    read = await api.get(f"{RECORDS}/{record.id}", headers=header)
    write = await api.post(
        f"{RECORDS}/{record.id}/manual-code", json={"code": CODE}, headers=header
    )

    assert read.status_code == 200
    assert write.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.CLEANER, UserRole.TECHNICIAN, UserRole.SUPER_ADMIN])
async def test_roles_without_access_permission_see_nothing(
    api, db_session, tenant_a, property_a, users_by_role_a, role
) -> None:
    """A guest's door code is not part of doing a cleaning or a repair.

    `SUPER_ADMIN` is here too, and deliberately: it holds no in-tenant operational permission
    until `saas-cross-tenant` decides what cross-tenant access looks like — the same line
    `reservations` and `properties-crud` already drew (`policy.py`).
    """
    record = await insert_access_record(db_session, tenant_a, property_a)
    header = auth_header(api, users_by_role_a[role])

    assert (await api.get(RECORDS, headers=header)).status_code == 403
    assert (await api.get(f"{RECORDS}/{record.id}", headers=header)).status_code == 403


@pytest.mark.asyncio
async def test_an_anonymous_request_is_refused(api) -> None:
    assert (await api.get(RECORDS)).status_code == 401


@pytest.mark.asyncio
async def test_the_filters_and_the_envelope(
    api, db_session, tenant_a, property_a, users_by_role_a
) -> None:
    reservation = await insert_reservation(db_session, tenant_a, property_a)
    await insert_access_record(db_session, tenant_a, property_a, reservation=reservation)
    await insert_access_record(
        db_session, tenant_a, property_a, status=AccessRecordStatus.DELIVERED
    )
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    filtered = await api.get(
        f"{RECORDS}?reservation_id={reservation.id}", headers=header
    )
    by_status = await api.get(f"{RECORDS}?status=DELIVERED", headers=header)
    paged = await api.get(f"{RECORDS}?page=1&per_page=1", headers=header)

    assert filtered.json()["total"] == 1
    assert by_status.json()["total"] == 1
    assert paged.json()["total"] == 2
    assert paged.json()["total_pages"] == 2
    assert len(paged.json()["data"]) == 1


@pytest.mark.asyncio
async def test_page_and_per_page_are_bounded(api, users_by_role_a) -> None:
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    assert (await api.get(f"{RECORDS}?per_page=1000", headers=header)).status_code == 422
    assert (
        await api.get(f"{RECORDS}?page=99999999999999999999", headers=header)
    ).status_code == 422


@pytest.mark.asyncio
async def test_the_request_cannot_choose_its_tenant(
    api, db_session, tenant_a, tenant_b, property_a, users_by_role_a
) -> None:
    """`extra="forbid"`: a `tenant_id` in the body is rejected, never honoured."""
    record = await insert_access_record(db_session, tenant_a, property_a)

    response = await api.post(
        f"{RECORDS}/{record.id}/manual-code",
        json={"code": CODE, "tenant_id": str(tenant_b.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 422
