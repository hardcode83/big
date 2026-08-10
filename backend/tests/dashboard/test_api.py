"""The two dashboard endpoints over the real app (`dashboard-api` R1, R2, task 6.3)."""

import uuid

import pytest

from app.auth.domain.enums import UserRole
from app.properties.infrastructure.models import PropertyModel
from tests.dashboard.conftest import auth_header, insert_property

COLLECTION = "/api/v1/dashboard/properties"
READERS = {UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER}


def _detail_url(prop: PropertyModel) -> str:
    return f"/api/v1/properties/{prop.id}/dashboard"


def _owner(api, users_by_role_a) -> dict[str, str]:
    return auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])


# --- the collection (R1) ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_collection_answers_the_prd_pagination_envelope(
    api, users_by_role_a, property_a
) -> None:
    response = await api.get(COLLECTION, headers=_owner(api, users_by_role_a))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "total", "page", "per_page", "total_pages"}
    assert (body["total"], body["page"], body["per_page"], body["total_pages"]) == (1, 1, 20, 1)


@pytest.mark.asyncio
async def test_a_card_carries_exactly_the_contract_fields(
    api, users_by_role_a, property_a
) -> None:
    """R1.2 — the fields of `PropertyDashboardCard` (`dto.ts:85-96`), no more, no fewer."""
    response = await api.get(COLLECTION, headers=_owner(api, users_by_role_a))

    card = response.json()["data"][0]
    assert set(card) == {
        "property_id",
        "property_code",
        "operational_state",
        "current_or_next_reservation",
        "cleaning_status",
        "open_incidents_count",
        "next_action",
        "last_event_label",
        "last_event_at",
    }


@pytest.mark.asyncio
async def test_the_reservation_key_is_present_and_null_not_omitted(
    api, users_by_role_a, property_a
) -> None:
    """R1.4, asserted on the serialised body rather than on the object — omission is a
    serialiser behaviour, so only the JSON can prove it."""
    response = await api.get(COLLECTION, headers=_owner(api, users_by_role_a))

    card = response.json()["data"][0]
    assert "current_or_next_reservation" in card
    assert card["current_or_next_reservation"] is None


@pytest.mark.asyncio
async def test_the_operational_state_is_the_canonical_literal(
    api, users_by_role_a, property_a
) -> None:
    """R1.3, and no colour anywhere in the payload."""
    response = await api.get(COLLECTION, headers=_owner(api, users_by_role_a))

    card = response.json()["data"][0]
    assert card["operational_state"] == "VACANT_READY"
    assert "color" not in response.text and "colour" not in response.text


@pytest.mark.asyncio
async def test_the_collection_paginates(api, db_session, tenant_a, users_by_role_a) -> None:
    for index in range(3):
        await insert_property(db_session, tenant_a, code=f"FLAT-{index}")

    first = await api.get(f"{COLLECTION}?page=1&per_page=2", headers=_owner(api, users_by_role_a))
    second = await api.get(f"{COLLECTION}?page=2&per_page=2", headers=_owner(api, users_by_role_a))

    assert first.json()["total"] == second.json()["total"] == 3
    assert len(first.json()["data"]) == 2
    assert len(second.json()["data"]) == 1
    ids = {card["property_id"] for card in first.json()["data"]}
    assert ids.isdisjoint({card["property_id"] for card in second.json()["data"]})


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["page=0", "per_page=0", "per_page=101", "page=100001"])
async def test_invalid_pagination_is_a_422_in_the_error_envelope(
    api, users_by_role_a, query: str
) -> None:
    """R1.5: the same bounds `GET /api/v1/properties` applies, and the §23 error envelope."""
    response = await api.get(f"{COLLECTION}?{query}", headers=_owner(api, users_by_role_a))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_an_empty_portfolio_is_an_empty_page_not_an_error(
    api, users_by_role_a, tenant_a
) -> None:
    response = await api.get(COLLECTION, headers=_owner(api, users_by_role_a))

    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "total": 0,
        "page": 1,
        "per_page": 20,
        "total_pages": 0,
    }


# --- the aggregate (R2) --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_detail_carries_exactly_the_contract_fields(
    api, users_by_role_a, property_a
) -> None:
    """R2.1 — the sections of PRD §9.2 (`dto.ts:161-174`)."""
    response = await api.get(_detail_url(property_a), headers=_owner(api, users_by_role_a))

    assert response.status_code == 200
    assert set(response.json()) == {
        "property_id",
        "property_code",
        "operational_state",
        "current_or_next_reservation",
        "guest",
        "access",
        "cleaning_status",
        "last_cleaning_photos",
        "open_incidents",
        "financial",
        "notes",
        "pending_approvals",
    }


@pytest.mark.asyncio
async def test_the_empty_blocks_are_empty_and_not_missing(
    api, users_by_role_a, property_a
) -> None:
    """R2.3/R2.4: the tables are real and empty today; the contract does not change when
    `maintenance` and `revenue` land."""
    body = (
        await api.get(_detail_url(property_a), headers=_owner(api, users_by_role_a))
    ).json()

    assert body["open_incidents"] == []
    assert body["pending_approvals"] == []
    assert body["last_cleaning_photos"] == []
    assert body["notes"] is None


@pytest.mark.asyncio
async def test_the_detail_never_exposes_a_storage_key(
    api, users_by_role_a, property_a
) -> None:
    """Rule 5 of `steering/security.md` — never an internal path."""
    response = await api.get(_detail_url(property_a), headers=_owner(api, users_by_role_a))

    assert "storage_key" not in response.text


# --- 404, indistinguishable (R2.2) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_property_and_a_neighbours_answer_the_very_same_404(
    api, users_by_role_a, property_b
) -> None:
    headers = _owner(api, users_by_role_a)

    unknown = await api.get(
        f"/api/v1/properties/{uuid.uuid4()}/dashboard", headers=headers
    )
    foreign = await api.get(_detail_url(property_b), headers=headers)

    assert unknown.status_code == foreign.status_code == 404
    assert unknown.json() == foreign.json()
    assert "PAJARITOS8" not in foreign.text


# --- authorisation (R1.6, R2.6) ------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_routes_refuse_an_anonymous_request(api, property_a) -> None:
    assert (await api.get(COLLECTION)).status_code == 401
    assert (await api.get(_detail_url(property_a))).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole))
async def test_only_property_readers_may_call_the_collection(
    api, users_by_role_a, property_a, role: UserRole
) -> None:
    response = await api.get(COLLECTION, headers=auth_header(api, users_by_role_a[role]))

    assert response.status_code == (200 if role in READERS else 403)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole))
async def test_only_property_readers_may_call_the_aggregate(
    api, users_by_role_a, property_a, role: UserRole
) -> None:
    response = await api.get(
        _detail_url(property_a), headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == (200 if role in READERS else 403)
