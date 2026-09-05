"""`GET /api/v1/timeline/{property_id}` (`dashboard-api` R4, R5, task 2.4)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.domain.enums import UserRole
from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.infrastructure.models import TimelineEventModel
from tests.auth.conftest import insert_user
from tests.timeline.conftest import auth_header

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


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
) -> TimelineEventModel:
    model = TimelineEventModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
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


def _url(prop: PropertyModel) -> str:
    return f"/api/v1/timeline/{prop.id}"


# --- shape (R4.1, R4.3) -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_answers_the_prd_pagination_envelope(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    await _add_event(db_session, tenant_a, property_a)

    response = await api.get(
        _url(property_a), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "total", "page", "per_page", "total_pages"}
    assert (body["total"], body["page"], body["per_page"], body["total_pages"]) == (1, 1, 20, 1)


@pytest.mark.asyncio
async def test_an_entry_carries_exactly_the_contract_fields_and_never_metadata(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    """R4.3: exactly the fields of `TimelineEntry`, and `metadata` is not serialised."""
    await _add_event(
        db_session, tenant_a, property_a, metadata={"secret": "must not appear", "x": 1}
    )

    response = await api.get(
        _url(property_a), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
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
    }
    assert "metadata" not in response.text
    assert "must not appear" not in response.text


@pytest.mark.asyncio
async def test_the_canonical_literals_travel_untranslated(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    """R5.5: `eventType`, `actorType` and `severity` are exact PRD values."""
    await _add_event(
        db_session,
        tenant_a,
        property_a,
        event_type=TimelineEventType.INCIDENT_CREATED,
        severity=TimelineSeverity.CRITICAL,
        actor_type=TimelineActorType.GUEST,
    )

    response = await api.get(
        _url(property_a), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    entry = response.json()["data"][0]
    assert entry["event_type"] == "INCIDENT_CREATED"
    assert entry["severity"] == "CRITICAL"
    assert entry["actor_type"] == "GUEST"


@pytest.mark.asyncio
async def test_entries_come_back_newest_first(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    old = await _add_event(db_session, tenant_a, property_a, created_at=NOW - timedelta(days=1))
    new = await _add_event(db_session, tenant_a, property_a, created_at=NOW)

    response = await api.get(
        _url(property_a), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert [entry["id"] for entry in response.json()["data"]] == [str(new.id), str(old.id)]


# --- language (R5.1) --------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "expected"),
    [("es", "Limpieza completada"), ("en", "Cleaning completed"), ("fr", "Limpieza completada")],
    ids=["spanish", "english", "unsupported-degrades-to-spanish"],
)
async def test_the_title_is_composed_in_the_users_language(
    api, db_session, tenant_a, property_a, language: str, expected: str
) -> None:
    """R5.1, and the stored English `title` is not what comes back.

    Sends **no** `X-Locale`, which is what keeps this the fallback case after
    `frontend-verification-fixes`: with nothing asked for, the stored row preference still
    decides, and an unsupported one still degrades to Spanish.
    """
    user = await insert_user(db_session, tenant=tenant_a, preferred_language=language)
    await _add_event(db_session, tenant_a, property_a)

    response = await api.get(_url(property_a), headers=auth_header(api, user))

    entry = response.json()["data"][0]
    assert entry["title"] == expected
    assert entry["title"] != "Stored English title"


#: The four combinations of `frontend-verification-fixes` R1.8: language the request asks
#: for x language stored on the row. A list and not a set — `steering/testing.md` forbids a
#: test that depends on the order it runs in, and iterating a set would hand pytest-xdist
#: workers the parametrised ids in different orders.
LOCALE_MATRIX = [
    ("es", "es", "Limpieza completada"),
    ("es", "en", "Limpieza completada"),
    ("en", "es", "Cleaning completed"),
    ("en", "en", "Cleaning completed"),
]
LOCALE_MATRIX_IDS = [f"asks-{asked}-row-{stored}" for asked, stored, _ in LOCALE_MATRIX]


@pytest.mark.asyncio
@pytest.mark.parametrize(("asked", "stored_language", "expected"), LOCALE_MATRIX, ids=LOCALE_MATRIX_IDS)
async def test_the_title_is_composed_in_the_language_the_request_asked_for(
    api,
    db_session,
    tenant_a,
    property_a,
    asked: str,
    stored_language: str,
    expected: str,
) -> None:
    """`frontend-verification-fixes` R1.1/R1.8: `X-Locale` decides, whatever the row says.

    The two mixed rows are the ones that carry the requirement: before this change the row
    won, so `asks-en-row-es` came back in Spanish on an English screen.
    """
    user = await insert_user(db_session, tenant=tenant_a, preferred_language=stored_language)
    await _add_event(db_session, tenant_a, property_a)

    response = await api.get(
        _url(property_a), headers={**auth_header(api, user), "X-Locale": asked}
    )

    entry = response.json()["data"][0]
    assert entry["title"] == expected
    assert entry["title"] != "Stored English title"


@pytest.mark.asyncio
@pytest.mark.parametrize(("asked", "stored_language", "expected"), LOCALE_MATRIX, ids=LOCALE_MATRIX_IDS)
async def test_the_requested_language_translates_no_canonical_literal(
    api,
    db_session,
    tenant_a,
    property_a,
    asked: str,
    stored_language: str,
    expected: str,
) -> None:
    """R1.6/R1.7 across the same matrix: R1 moves where the locale comes from, not what is
    translated. `description` is operator-written text and `event_type`/`actor_type`/
    `severity` are contract literals, so neither moves with the language; and the stored
    `title` column stays the English audit copy of R1.7."""
    user = await insert_user(db_session, tenant=tenant_a, preferred_language=stored_language)
    stored = await _add_event(db_session, tenant_a, property_a)

    response = await api.get(
        _url(property_a), headers={**auth_header(api, user), "X-Locale": asked}
    )

    entry = response.json()["data"][0]
    assert entry["title"] == expected, "sanity: the matrix row must actually have taken effect"
    assert entry["description"] == "Stored description"
    assert entry["event_type"] == "CLEANING_COMPLETED"
    assert entry["actor_type"] == "SYSTEM"
    assert entry["severity"] == "INFO"

    await db_session.refresh(stored)
    assert stored.title == "Stored English title"


@pytest.mark.asyncio
async def test_the_stored_title_is_not_modified_by_being_read(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    """R5.3: the column stays the English audit copy."""
    stored = await _add_event(db_session, tenant_a, property_a)

    await api.get(
        _url(property_a), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )
    await db_session.refresh(stored)

    assert stored.title == "Stored English title"


# --- filters (R4.2) ---------------------------------------------------------------------


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
        response = await api.get(f"{_url(property_a)}?{query}", headers=headers)
        assert response.status_code == 200, query
        assert [entry["id"] for entry in response.json()["data"]] == [str(wanted.id)], query


@pytest.mark.asyncio
async def test_the_range_filters_use_the_contract_names_from_and_to(
    api, db_session, tenant_a, users_by_role_a, property_a
) -> None:
    """`dto.ts:111-117` spells the bounds `from`/`to`; `from` is a Python keyword, so the
    handler reaches them through an alias — this is what pins the wire names."""
    inside = await _add_event(db_session, tenant_a, property_a, created_at=NOW)
    await _add_event(db_session, tenant_a, property_a, created_at=NOW - timedelta(days=5))

    response = await api.get(
        f"{_url(property_a)}?from=2026-08-08T00:00:00Z&to=2026-08-10T00:00:00Z",
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert [entry["id"] for entry in response.json()["data"]] == [str(inside.id)]


@pytest.mark.asyncio
async def test_an_inverted_range_is_a_422_in_the_error_envelope(
    api, users_by_role_a, property_a
) -> None:
    response = await api.get(
        f"{_url(property_a)}?from=2026-08-10T00:00:00Z&to=2026-08-01T00:00:00Z",
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert response.status_code == 422
    assert set(response.json()["error"]) == {"code", "message", "details"}


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["page=0", "per_page=0", "per_page=101", "page=100001"])
async def test_out_of_range_pagination_is_a_422_in_the_error_envelope(
    api, users_by_role_a, property_a, query: str
) -> None:
    response = await api.get(
        f"{_url(property_a)}?{query}",
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- 404, indistinguishable (R4.5) ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_property_that_does_not_exist_answers_404(
    api, users_by_role_a
) -> None:
    response = await api.get(
        f"/api/v1/timeline/{uuid.uuid4()}",
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_property_of_another_tenant_answers_the_very_same_404(
    api, db_session, tenant_b, users_by_role_a, property_b
) -> None:
    """R4.5: indistinguishable between the two, body included — otherwise the status code
    tells a caller which of a neighbour's ids are real."""
    await _add_event(db_session, tenant_b, property_b)
    headers = auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])

    unknown = await api.get(f"/api/v1/timeline/{uuid.uuid4()}", headers=headers)
    foreign = await api.get(_url(property_b), headers=headers)

    assert unknown.status_code == foreign.status_code == 404
    assert unknown.json() == foreign.json()


# --- authorisation (R4.6) ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_refuses_an_anonymous_request(api, property_a) -> None:
    assert (await api.get(_url(property_a))).status_code == 401


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
    api, users_by_role_a, property_a, role: UserRole, expected: int
) -> None:
    """`READ_PROPERTIES`: a property's history is gated by the same capability as the
    property. A cleaner has no business reading a flat's whole operational history."""
    response = await api.get(_url(property_a), headers=auth_header(api, users_by_role_a[role]))

    assert response.status_code == expected


@pytest.mark.asyncio
async def test_a_role_without_the_permission_cannot_tell_a_real_property_from_a_fake_one(
    api, users_by_role_a, property_a
) -> None:
    """403 before 404: the permission check runs as a dependency, so an unauthorised caller
    learns nothing about which ids exist."""
    headers = auth_header(api, users_by_role_a[UserRole.CLEANER])

    real = await api.get(_url(property_a), headers=headers)
    fake = await api.get(f"/api/v1/timeline/{uuid.uuid4()}", headers=headers)

    assert real.status_code == fake.status_code == 403
