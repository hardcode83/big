"""`GET /api/v1/timeline` (`dashboard-activity-feed` R1, R2, R3, R4).

Structure mirrors `tests/timeline/test_api.py`, the per-property sibling: same fixtures,
same `_add_event` helper, same per-role matrix. What differs is scope — every property of
the tenant, not one — and the three identity fields the tenant-wide entry carries that the
per-property one does not.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.auth.domain.enums import UserRole
from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.infrastructure.models import TimelineEventModel
from tests.auth.conftest import insert_user
from tests.timeline.conftest import auth_header

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

URL = "/api/v1/timeline"


@pytest_asyncio.fixture
async def property_a2(db_session, tenant_a) -> PropertyModel:
    """A second property of tenant A — what makes "merges across properties" testable."""
    prop = PropertyModel(
        tenant_id=tenant_a.id, name="Alcala 20", internal_code="ALCALA20", max_guests=6
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


async def _add_event(
    db_session,
    tenant: TenantModel,
    prop: PropertyModel,
    *,
    created_at: datetime = NOW,
    event_type: TimelineEventType = TimelineEventType.CLEANING_COMPLETED,
    severity: TimelineSeverity = TimelineSeverity.INFO,
    actor_type: TimelineActorType = TimelineActorType.SYSTEM,
    metadata: dict | None = None,
    property_id: uuid.UUID | None = None,
) -> TimelineEventModel:
    model = TimelineEventModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=property_id if property_id is not None else prop.id,
        actor_type=actor_type,
        event_type=event_type,
        severity=severity,
        title="Stored English title",
        description="Stored description",
        created_at=created_at,
        metadata_=metadata,
    )
    db_session.add(model)
    await db_session.flush()
    return model


# --- shape (R3.1, R3.3) ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_answers_the_prd_pagination_envelope(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    await _add_event(db_session, tenant_a, property_a)

    response = await api.get(
        URL, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "total", "page", "per_page", "total_pages"}
    assert (body["total"], body["page"], body["per_page"], body["total_pages"]) == (1, 1, 20, 1)


@pytest.mark.asyncio
async def test_an_entry_carries_the_contract_fields_plus_identity_and_never_metadata(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    """R3.1, R3.3: the seven `TimelineEntry` fields plus the three identity fields, and
    `metadata` is not serialised."""
    await _add_event(
        db_session, tenant_a, property_a, metadata={"secret": "must not appear", "x": 1}
    )

    response = await api.get(
        URL, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    entry = response.json()["data"][0]
    assert set(entry) == {
        "id",
        "occurred_at",
        "actor_type",
        "event_type",
        "severity",
        "title",
        "description",
        "property_id",
        "property_name",
        "property_internal_code",
    }
    assert entry["property_id"] == str(property_a.id)
    assert entry["property_name"] == property_a.name
    assert entry["property_internal_code"] == property_a.internal_code
    assert "metadata" not in response.text
    assert "must not appear" not in response.text


@pytest.mark.asyncio
async def test_the_canonical_literals_travel_untranslated(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    await _add_event(
        db_session,
        tenant_a,
        property_a,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.CRITICAL,
        actor_type=TimelineActorType.GUEST,
    )

    response = await api.get(
        URL, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    entry = response.json()["data"][0]
    assert entry["event_type"] == "INCIDENT_CREATED"
    assert entry["severity"] == "CRITICAL"
    assert entry["actor_type"] == "GUEST"


@pytest.mark.asyncio
async def test_entries_come_back_newest_first_across_properties(
    api, db_session, tenant_a, users_by_role_a, property_a, property_a2
) -> None:
    old = await _add_event(db_session, tenant_a, property_a, created_at=NOW - timedelta(days=1))
    new = await _add_event(db_session, tenant_a, property_a2, created_at=NOW)

    response = await api.get(
        URL, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert [entry["id"] for entry in response.json()["data"]] == [str(new.id), str(old.id)]


@pytest.mark.asyncio
async def test_the_entry_id_is_the_tiebreak_when_timestamps_collide(
    api, db_session, tenant_a, users_by_role_a, property_a, property_a2
) -> None:
    first = await _add_event(db_session, tenant_a, property_a, created_at=NOW)
    second = await _add_event(db_session, tenant_a, property_a2, created_at=NOW)
    expected = sorted([first.id, second.id], reverse=True)

    response = await api.get(
        URL, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert [uuid.UUID(entry["id"]) for entry in response.json()["data"]] == expected


# --- language (R4.2 title composition) ---------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "expected"),
    [("es", "Limpieza completada"), ("en", "Cleaning completed"), ("fr", "Limpieza completada")],
    ids=["spanish", "english", "unsupported-degrades-to-spanish"],
)
async def test_the_title_is_composed_in_the_users_language(
    api, db_session, tenant_a, property_a, language: str, expected: str
) -> None:
    user = await insert_user(db_session, tenant=tenant_a, preferred_language=language)
    await _add_event(db_session, tenant_a, property_a)

    response = await api.get(URL, headers=auth_header(api, user))

    entry = response.json()["data"][0]
    assert entry["title"] == expected
    assert entry["title"] != "Stored English title"


@pytest.mark.asyncio
async def test_the_description_is_returned_verbatim(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    await _add_event(db_session, tenant_a, property_a)

    response = await api.get(
        URL, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.json()["data"][0]["description"] == "Stored description"


# --- filters (R4.2) -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_filter_narrows_the_result(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    wanted = await _add_event(
        db_session,
        tenant_a,
        property_a,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.CRITICAL,
        actor_type=TimelineActorType.GUEST,
    )
    await _add_event(db_session, tenant_a, property_a)
    headers = auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])

    for query in (
        "event_type=INCIDENT_CREATED",
        "severity=CRITICAL",
        "actor_type=GUEST",
    ):
        response = await api.get(f"{URL}?{query}", headers=headers)
        assert response.status_code == 200, query
        assert [entry["id"] for entry in response.json()["data"]] == [str(wanted.id)], query


@pytest.mark.asyncio
async def test_the_filters_and_combine(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    wanted = await _add_event(
        db_session,
        tenant_a,
        property_a,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.CRITICAL,
        actor_type=TimelineActorType.GUEST,
    )
    # Same event_type, different severity — must be excluded by the AND-combination.
    await _add_event(
        db_session,
        tenant_a,
        property_a,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.INFO,
        actor_type=TimelineActorType.GUEST,
    )

    response = await api.get(
        f"{URL}?event_type=INCIDENT_CREATED&severity=CRITICAL&actor_type=GUEST",
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert [entry["id"] for entry in response.json()["data"]] == [str(wanted.id)]


@pytest.mark.asyncio
async def test_the_range_filters_use_the_contract_names_from_and_to(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    inside = await _add_event(db_session, tenant_a, property_a, created_at=NOW)
    await _add_event(db_session, tenant_a, property_a, created_at=NOW - timedelta(days=5))

    response = await api.get(
        f"{URL}?from=2026-08-08T00:00:00Z&to=2026-08-10T00:00:00Z",
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert [entry["id"] for entry in response.json()["data"]] == [str(inside.id)]


@pytest.mark.asyncio
async def test_an_inverted_range_is_a_422_in_the_error_envelope(
    api, users_by_role_a
) -> None:
    response = await api.get(
        f"{URL}?from=2026-08-10T00:00:00Z&to=2026-08-01T00:00:00Z",
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert response.status_code == 422
    assert set(response.json()["error"]) == {"code", "message", "details"}


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["page=0", "per_page=0", "per_page=101", "page=100001"])
async def test_out_of_range_pagination_is_a_422_in_the_error_envelope(
    api, users_by_role_a, query: str
) -> None:
    response = await api.get(
        f"{URL}?{query}",
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- empty tenant / no property_id required (R1.3, R1.4) ----------------------------------


@pytest.mark.asyncio
async def test_a_tenant_with_no_properties_answers_200_with_an_empty_page(
    api, users_by_role_a
) -> None:
    response = await api.get(
        URL, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_a_tenant_with_properties_but_no_events_answers_200_with_an_empty_page(
    api, users_by_role_a, property_a
) -> None:
    response = await api.get(
        URL, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_the_route_accepts_no_property_id(api, users_by_role_a) -> None:
    """`GET /api/v1/timeline` resolves on its own — no id segment required, and it is a
    structurally distinct path from `/api/v1/timeline/{property_id}` (design D1)."""
    response = await api.get(
        "/api/v1/timeline", headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.status_code == 200


# --- authorisation (R4.1) ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_refuses_an_anonymous_request(api) -> None:
    assert (await api.get(URL)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (UserRole.TENANT_OWNER, 200),
        (UserRole.PROPERTY_MANAGER, 200),
        (UserRole.CLEANER, 403),
        (UserRole.TECHNICIAN, 403),
        (UserRole.SUPER_ADMIN, 403),
    ],
)
async def test_the_route_is_gated_by_read_properties(
    api, users_by_role_a, role: UserRole, expected: int
) -> None:
    response = await api.get(URL, headers=auth_header(api, users_by_role_a[role]))

    assert response.status_code == expected


# --- tenant isolation (R4.3, task 3.5) ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_neighbour_tenants_property_and_events_never_appear(
    api, db_session, tenant_a, tenant_b, users_by_role_a, property_a, property_b
) -> None:
    """A neighbour tenant with its own property AND events: none of it appears in the
    caller's feed or its `total`."""
    mine = await _add_event(db_session, tenant_a, property_a)
    await _add_event(db_session, tenant_b, property_b)

    response = await api.get(
        URL, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [entry["id"] for entry in body["data"]] == [str(mine.id)]


# --- identity-resolution edge case (R3.1, design D6, task 3.6) ------------------------------


@pytest.mark.asyncio
async def test_a_dangling_cross_tenant_property_id_degrades_to_null_never_a_500(
    api, db_session, tenant_a, users_by_role_a, property_a, property_b
) -> None:
    """An event whose `property_id` does not resolve within the tenant — here, a
    cross-tenant reference inserted directly at the DB level, the same technique
    `reservation-property-identity`'s `tests/reservations/test_identity_isolation.py` uses
    (`property_id` is a plain FK to `properties.id`, so this is reachable on disk) — still
    appears in the feed with `property_name`/`property_internal_code: null`, never a `500`
    and never dropped."""
    event = await _add_event(db_session, tenant_a, property_a, property_id=property_b.id)

    response = await api.get(
        URL, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    entry = body["data"][0]
    assert entry["id"] == str(event.id)
    assert entry["property_id"] == str(property_b.id)
    assert entry["property_name"] is None
    assert entry["property_internal_code"] is None
