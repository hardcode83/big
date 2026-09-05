"""The dashboard endpoints over the real app (`dashboard-api` R1, R2; `dashboard-operational-
kpis` R1-R4, task 6.4; `dashboard-occupancy-series` R1, R4)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.auth.domain import policy
from app.auth.domain.enums import UserRole
from app.auth.domain.policy import Permission
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.infrastructure.models import CleaningTaskModel
from app.maintenance.domain.enums import (
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalRelatedType,
)
from app.maintenance.infrastructure.models import IncidentModel, OwnerApprovalModel
from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.infrastructure.models import TimelineEventModel
from tests.auth.conftest import insert_user
from tests.cleaning.conftest import insert_template
from tests.dashboard.conftest import TODAY, auth_header, insert_property

COLLECTION = "/api/v1/dashboard/properties"
OPERATIONAL_KPIS = "/api/v1/dashboard/operational-kpis"
OCCUPANCY_SERIES = "/api/v1/dashboard/occupancy-series"
READERS = {UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER}

# `TODAY` is a Sunday (2026-08-09); the ISO week it closes runs Monday to Sunday.
WEEK_START = date(2026, 8, 3)
WEEK_END = date(2026, 8, 9)


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
async def test_the_collection_and_the_aggregate_are_not_cacheable_by_a_shared_cache(
    api, users_by_role_a, property_a
) -> None:
    """Composed text varies on `X-Locale`, a request header no shared cache keys on
    (security review, round 6): a stale response for one reader's locale must never be
    served to another from a cache. `private, no-store` on both routes, matching the
    existing `app/provenance/api/router.py` precedent."""
    collection = await api.get(COLLECTION, headers=_owner(api, users_by_role_a))
    aggregate = await api.get(_detail_url(property_a), headers=_owner(api, users_by_role_a))

    assert collection.headers["cache-control"] == "private, no-store"
    assert aggregate.headers["cache-control"] == "private, no-store"


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


# --- language (`frontend-verification-fixes` R1.1, R1.6, R1.7, R1.8) ----------------------

#: The four combinations R1.8 names: language the request asks for x language stored on the
#: row. A list of pairs and not a product over sets — `steering/testing.md` forbids a test
#: that depends on the order it runs in, and set iteration order would hand pytest-xdist
#: workers different parametrised ids for the same case.
LOCALE_MATRIX = [("es", "es"), ("es", "en"), ("en", "es"), ("en", "en")]
LOCALE_MATRIX_IDS = [f"asks-{asked}-row-{stored}" for asked, stored in LOCALE_MATRIX]

#: Keyed by the language **asked for**, never by the row's: that is the whole assertion.
EXPECTED_LABELS = {
    "es": {
        "cleaning_status": "Limpieza en curso",
        "next_action_label": "Asignar limpiadora",
        "responsible": "Gestor",
        "last_event_label": "Limpieza completada",
        # `access.label` (`ACCESS_STATUS_LABELS[ReservationAccessStatus.PENDING]`),
        # `open_incidents[0].title` (`INCIDENT_TITLE_LABELS[IncidentCategory.OTHER]`, the
        # column's own default) and `pending_approvals[0].label`
        # (`APPROVAL_LABELS[OwnerApprovalRelatedType.OTHER]`) — R1.8's three fields the
        # aggregate composes besides `cleaning_status`, seeded by `_seed_composed_text`.
        "access_label": "Acceso pendiente",
        "incident_title": "Otra incidencia",
        "approval_label": "Aprobación pendiente",
    },
    "en": {
        "cleaning_status": "Cleaning in progress",
        "next_action_label": "Assign a cleaner",
        "responsible": "Manager",
        "last_event_label": "Cleaning completed",
        "access_label": "Access pending",
        "incident_title": "Other incident",
        "approval_label": "Pending approval",
    },
}

#: What the operator typed, in the language they typed it. R1.6 keeps it out of the
#: translation, so it must read the same whatever the request asks for.
STORED_INCIDENT_TITLE = "Boiler is dead"


async def _seed_composed_text(db_session, tenant, prop) -> None:
    """Puts a value behind every composed label on both routes, so a matrix row that
    silently produced `null` could not pass by asserting `None == None`."""
    prop.current_operational_state = PropertyOperationalState.AWAITING_CLEANING
    template = await insert_template(db_session, tenant, name="Estándar")
    db_session.add(
        CleaningTaskModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            property_id=prop.id,
            checklist_template_id=template.id,
            status=CleaningTaskStatus.IN_PROGRESS,
            scheduled_start=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC),
        )
    )
    db_session.add(
        TimelineEventModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            property_id=prop.id,
            actor_type=TimelineActorType.SYSTEM,
            event_type=TimelineEventType.CLEANING_COMPLETED,
            severity=TimelineSeverity.INFO,
            title="Stored English title",
            description="Stored description",
            created_at=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC),
        )
    )
    db_session.add(
        IncidentModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            property_id=prop.id,
            source=IncidentSource.GUEST,
            title=STORED_INCIDENT_TITLE,
            description="No hot water.",
            status=IncidentStatus.OPEN,
            severity=IncidentSeverity.CRITICAL,
            # No explicit `category=`: it defaults to `IncidentCategory.OTHER`, which is what
            # `EXPECTED_LABELS[...]["incident_title"]` is keyed to render.
        )
    )
    # A live stay, so `access` resolves instead of coming back `null` (R1.8's second
    # composed-text field on this route). `access_status` stays at its column default
    # (`ReservationAccessStatus.PENDING`), which is what `EXPECTED_LABELS[...]["access_label"]`
    # renders.
    db_session.add(
        ReservationModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            property_id=prop.id,
            guest_id=None,
            channel=ReservationChannel.DIRECT,
            external_pms_id=f"LOCALE-SEED-{uuid.uuid4().hex[:8]}",
            status=ReservationStatus.CONFIRMED,
            check_in_date=TODAY,
            check_out_date=TODAY + timedelta(days=1),
            nights=1,
            adults=2,
        )
    )
    # A pending approval, so `pending_approvals` is non-empty (R1.8's third composed-text
    # field on this route). `related_type=OTHER` keeps the label generic and matches
    # `EXPECTED_LABELS[...]["approval_label"]`.
    db_session.add(
        OwnerApprovalModel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            property_id=prop.id,
            related_type=OwnerApprovalRelatedType.OTHER,
            related_id=uuid.uuid4(),
            amount=Decimal("42.00"),
            reason="Seeded for R1.8 locale coverage.",
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(("asked", "stored_language"), LOCALE_MATRIX, ids=LOCALE_MATRIX_IDS)
async def test_the_collection_composes_in_the_language_the_request_asked_for(
    api, db_session, tenant_a, property_a, asked: str, stored_language: str
) -> None:
    """R1.1/R1.8 on `GET /dashboard/properties`.

    The two mixed rows are the ones that carry the requirement: before this change the row
    won, so `asks-en-row-es` served a Spanish card to an English screen.
    """
    user = await insert_user(db_session, tenant=tenant_a, preferred_language=stored_language)
    await _seed_composed_text(db_session, tenant_a, property_a)
    expected = EXPECTED_LABELS[asked]

    response = await api.get(
        COLLECTION, headers={**auth_header(api, user), "X-Locale": asked}
    )

    assert response.status_code == 200
    card = response.json()["data"][0]
    assert card["cleaning_status"] == expected["cleaning_status"]
    assert card["next_action"]["label"] == expected["next_action_label"]
    assert card["next_action"]["responsible"] == expected["responsible"]
    assert card["last_event_label"] == expected["last_event_label"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("asked", "stored_language"), LOCALE_MATRIX, ids=LOCALE_MATRIX_IDS)
async def test_the_aggregate_composes_in_the_language_the_request_asked_for(
    api, db_session, tenant_a, property_a, asked: str, stored_language: str
) -> None:
    """R1.1/R1.8 on `GET /properties/{id}/dashboard`."""
    user = await insert_user(db_session, tenant=tenant_a, preferred_language=stored_language)
    await _seed_composed_text(db_session, tenant_a, property_a)
    expected = EXPECTED_LABELS[asked]

    response = await api.get(
        _detail_url(property_a), headers={**auth_header(api, user), "X-Locale": asked}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cleaning_status"] == expected["cleaning_status"]
    # The three other independent text fields this route composes through the same
    # `locale` parameter (R1.8): a regression that hardcodes any one of them would leave
    # `cleaning_status` alone green and go undetected without these.
    assert body["access"]["label"] == expected["access_label"]
    assert body["open_incidents"][0]["title"] == expected["incident_title"]
    assert body["pending_approvals"][0]["label"] == expected["approval_label"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("asked", "stored_language"), LOCALE_MATRIX, ids=LOCALE_MATRIX_IDS)
async def test_the_requested_language_translates_no_canonical_literal(
    api, db_session, tenant_a, property_a, asked: str, stored_language: str
) -> None:
    """R1.6/R1.7: R1 moves where the locale comes from, not what gets translated.

    `operational_state` is a contract literal, the incident's stored `title` is
    operator-written text, and the timeline's stored `title` column stays the English audit
    copy — none of the three moves with the language.
    """
    user = await insert_user(db_session, tenant=tenant_a, preferred_language=stored_language)
    await _seed_composed_text(db_session, tenant_a, property_a)

    collection = await api.get(
        COLLECTION, headers={**auth_header(api, user), "X-Locale": asked}
    )
    detail = await api.get(
        _detail_url(property_a), headers={**auth_header(api, user), "X-Locale": asked}
    )

    card = collection.json()["data"][0]
    assert card["cleaning_status"] == EXPECTED_LABELS[asked]["cleaning_status"], (
        "sanity: the matrix row must actually have taken effect"
    )
    assert card["operational_state"] == "AWAITING_CLEANING"
    assert detail.json()["operational_state"] == "AWAITING_CLEANING"

    stored_event = (
        await db_session.execute(select(TimelineEventModel).where(
            TimelineEventModel.property_id == property_a.id
        ))
    ).scalar_one()
    assert stored_event.title == "Stored English title"

    stored_incident = (
        await db_session.execute(select(IncidentModel).where(
            IncidentModel.property_id == property_a.id
        ))
    ).scalar_one()
    assert stored_incident.title == STORED_INCIDENT_TITLE


# --- operational KPIs (`dashboard-operational-kpis` R1, R2, R3, R4) ------------------------


@pytest.mark.asyncio
async def test_the_three_keys_are_always_present_null_included(
    api, users_by_role_a
) -> None:
    """R4.3: the door-gate role (`TENANT_OWNER`/`PROPERTY_MANAGER`) holds all three source
    permissions, so this pins presence and shape; the `null` case is proven at the use-case
    level (`test_operational_kpis.py`), since no seeded role here has `READ_PROPERTIES`
    without also holding all three source permissions."""
    response = await api.get(OPERATIONAL_KPIS, headers=_owner(api, users_by_role_a))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"cleanings_today", "upcoming_checkins", "open_incidents"}


@pytest.mark.asyncio
async def test_an_empty_tenant_gets_zeroes_not_nulls(api, users_by_role_a) -> None:
    body = (await api.get(OPERATIONAL_KPIS, headers=_owner(api, users_by_role_a))).json()

    assert body["cleanings_today"] == 0
    assert body["upcoming_checkins"] == 0
    assert body["open_incidents"] == {"total": 0, "urgent": 0}


@pytest.mark.asyncio
async def test_a_happy_path_response_returns_the_right_numbers(
    api, db_session, tenant_a, property_a, users_by_role_a
) -> None:
    template = await insert_template(db_session, tenant_a, name="Estándar")
    db_session.add(
        CleaningTaskModel(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            checklist_template_id=template.id,
            status=CleaningTaskStatus.IN_PROGRESS,
            scheduled_start=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC),
        )
    )
    db_session.add(
        ReservationModel(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            channel=ReservationChannel.DIRECT,
            status=ReservationStatus.CONFIRMED,
            check_in_date=TODAY + timedelta(days=3),
            check_out_date=TODAY + timedelta(days=5),
            nights=2,
            adults=2,
        )
    )
    db_session.add(
        IncidentModel(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            source=IncidentSource.GUEST,
            title="Boiler is dead",
            description="No hot water.",
            status=IncidentStatus.OPEN,
            severity=IncidentSeverity.CRITICAL,
        )
    )
    db_session.add(
        IncidentModel(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            source=IncidentSource.GUEST,
            title="Squeaky door",
            description="The balcony door squeaks.",
            status=IncidentStatus.OPEN,
            severity=IncidentSeverity.LOW,
        )
    )
    await db_session.flush()

    body = (await api.get(OPERATIONAL_KPIS, headers=_owner(api, users_by_role_a))).json()

    assert body["cleanings_today"] == 1
    assert body["upcoming_checkins"] == 1
    assert body["open_incidents"] == {"total": 2, "urgent": 1}


@pytest.mark.asyncio
async def test_both_dashboard_routes_refuse_an_anonymous_request_including_kpis(api) -> None:
    assert (await api.get(OPERATIONAL_KPIS)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole))
async def test_only_property_readers_may_call_the_operational_kpis(
    api, users_by_role_a, role: UserRole
) -> None:
    response = await api.get(OPERATIONAL_KPIS, headers=auth_header(api, users_by_role_a[role]))

    assert response.status_code == (200 if role in READERS else 403)


# --- occupancy series (`dashboard-occupancy-series` R1, R4) --------------------------------


@pytest.mark.asyncio
async def test_the_series_is_seven_points_monday_to_sunday_with_exact_fields(
    api, db_session, tenant_a, property_a, users_by_role_a
) -> None:
    """R1.2, R1.4: the fields on the wire are exactly the four the domain carries — no
    colour, no weekday label — and the week runs Monday (`WEEK_START`) to Sunday
    (`TODAY`), whichever day of the week `TODAY` itself falls on."""
    await insert_property(db_session, tenant_a, code="FLAT-2")
    db_session.add(
        ReservationModel(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            channel=ReservationChannel.DIRECT,
            status=ReservationStatus.CONFIRMED,
            check_in_date=WEEK_START,
            check_out_date=WEEK_START + timedelta(days=2),
            nights=2,
            adults=2,
        )
    )
    await db_session.flush()

    response = await api.get(OCCUPANCY_SERIES, headers=_owner(api, users_by_role_a))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data"}
    points = body["data"]
    assert points is not None
    assert len(points) == 7
    assert [point["date"] for point in points] == [
        (WEEK_START + timedelta(days=offset)).isoformat() for offset in range(7)
    ]
    for point in points:
        assert set(point) == {
            "date",
            "occupied_properties",
            "total_properties",
            "occupancy_pct",
        }
        assert point["total_properties"] == 2

    # `property_a`'s stay covers Monday and Tuesday nights; Wednesday is checkout day, so
    # only two of the seven points are occupied.
    occupied_dates = {point["date"] for point in points if point["occupied_properties"] == 1}
    assert occupied_dates == {WEEK_START.isoformat(), (WEEK_START + timedelta(days=1)).isoformat()}
    for point in points:
        expected_pct = 50.0 if point["date"] in occupied_dates else 0.0
        assert point["occupancy_pct"] == expected_pct


@pytest.mark.asyncio
async def test_an_empty_portfolio_answers_null_percentage_on_every_point(
    api, users_by_role_a
) -> None:
    """R1.3: a tenant with no active properties cannot answer a division by zero."""
    response = await api.get(OCCUPANCY_SERIES, headers=_owner(api, users_by_role_a))

    assert response.status_code == 200
    points = response.json()["data"]
    assert len(points) == 7
    assert all(point["total_properties"] == 0 for point in points)
    assert all(point["occupancy_pct"] is None for point in points)


@pytest.mark.asyncio
async def test_a_blocked_property_counts_as_occupied_through_the_days_it_stays_blocked(
    api, db_session, tenant_a, property_a, users_by_role_a
) -> None:
    """R2.1's second condition, exercised through the real route rather than the unit
    fixtures of `test_occupancy_series.py`: a property blocked by its owner before the week
    and never released counts as occupied on every one of the seven points."""
    await SqlAlchemyPropertyStateTransitionRepository(db_session).add(
        tenant_a.id,
        PropertyStateTransition(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            property_id=property_a.id,
            from_state=PropertyOperationalState.VACANT_READY,
            to_state=PropertyOperationalState.BLOCKED_BY_OWNER,
            triggered_by=StateTransitionTriggeredBy.SYSTEM,
            created_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
            reason="owner blocked the flat",
        ),
    )

    response = await api.get(OCCUPANCY_SERIES, headers=_owner(api, users_by_role_a))

    assert response.status_code == 200
    points = response.json()["data"]
    assert all(point["occupied_properties"] == 1 for point in points)
    assert all(point["total_properties"] == 1 for point in points)
    assert all(point["occupancy_pct"] == 100.0 for point in points)


@pytest.mark.asyncio
async def test_an_anonymous_request_is_refused_for_the_occupancy_series(api) -> None:
    assert (await api.get(OCCUPANCY_SERIES)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole))
async def test_only_property_readers_may_call_the_occupancy_series(
    api, users_by_role_a, role: UserRole
) -> None:
    response = await api.get(
        OCCUPANCY_SERIES, headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == (200 if role in READERS else 403)


@pytest.mark.asyncio
async def test_the_data_key_is_null_for_a_role_without_read_reservations(
    api, db_session, tenant_a, property_a, users_by_role_a, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4.3, surfaced through the real route.

    No seeded role holds `READ_PROPERTIES` without also holding `READ_RESERVATIONS` — the
    same situation `test_the_three_keys_are_always_present_null_included` above records for
    `operational-kpis` — so the door-gate role's permissions are stripped down to exactly
    `READ_PROPERTIES` for this one request. The redaction path itself (zero domain queries
    when the check fails) is proven in `tests/dashboard/test_use_cases.py`; this test is
    only responsible for the wire shape: `data: null`, not an omitted key, not a 403.
    """
    monkeypatch.setattr(
        policy,
        "ROLE_PERMISSIONS",
        {
            **policy.ROLE_PERMISSIONS,
            UserRole.TENANT_OWNER: frozenset({Permission.READ_PROPERTIES}),
        },
    )

    response = await api.get(OCCUPANCY_SERIES, headers=_owner(api, users_by_role_a))

    assert response.status_code == 200
    assert response.json() == {"data": None}
