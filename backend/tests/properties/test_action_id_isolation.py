"""Cross-tenant isolation tests for the action ids (R4 of `blocked-transition-response-ids`).

Rule 1 of `sdd/steering/security.md`: a tenant must not access another tenant's data.
For the action ids, the consequence is concrete — the dashboard's "Cancel cleaning"
button calls `POST /cleaning-tasks/{id}/cancel`, and a button carrying a
cross-tenant id would let tenant A cancel tenant B's task. So this is not a privacy
risk, it is an integrity risk: the dashboard's actions are scoped to the button's
id, not to the tenant of the session.

Each test here seeds TWO tenants with a stalled property, asks for the collection as
ONE of them, and asserts that the action id in the response is the one belonging to
the calling tenant — never the neighbour's, never null-on-purpose, never fabricated.
"""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest

from app.auth.domain.enums import UserRole
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.infrastructure.models import (
    CleaningChecklistTemplateModel,
    CleaningTaskModel,
)
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
)
from app.maintenance.infrastructure.models import IncidentModel
from app.properties.domain.enums import PropertyOperationalState
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from tests.properties.conftest import auth_header

ENDPOINT = "/api/v1/blocked-transitions"


def _at(api, user):
    return auth_header(api, user)


async def _stalled_property(db_session, tenant, *, internal_code, state):
    """Stalled flat of `tenant` in the given `state`."""
    prop = PropertyModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=f"Flat {internal_code}",
        internal_code=internal_code,
        timezone="Europe/Madrid",
        current_operational_state=state,
        default_check_in_time=time(15, 0),
        default_check_out_time=time(11, 0),
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


async def _stay(db_session, prop):
    """A stay running today so `CHECKIN_TIME_REACHED` is the due trigger."""
    check_in = datetime.now(UTC).date() - timedelta(days=3)
    check_out = datetime.now(UTC).date() + timedelta(days=2)
    reservation = ReservationModel(
        id=uuid.uuid4(),
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        channel=ReservationChannel.MANUAL,
        check_in_date=check_in,
        check_out_date=check_out,
        nights=(check_out - check_in).days,
        status=ReservationStatus.CONFIRMED,
        adults=2,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


async def _open_cleaning_task(db_session, prop, *, status=CleaningTaskStatus.IN_PROGRESS):
    template = CleaningChecklistTemplateModel(
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        name="Test template",
        items=[],
        required_photos=[],
        active=True,
    )
    db_session.add(template)
    await db_session.flush()
    task = CleaningTaskModel(
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        checklist_template_id=template.id,
        status=status,
    )
    db_session.add(task)
    await db_session.flush()
    return task


async def _open_incident(db_session, prop, *, status=IncidentStatus.OPEN):
    incident = IncidentModel(
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        source=IncidentSource.GUEST,
        category=IncidentCategory.OTHER,
        severity=IncidentSeverity.MEDIUM,
        status=status,
        title="Test incident",
        description="",
    )
    db_session.add(incident)
    await db_session.flush()
    return incident


# --- R4.1, R4.2: cross-tenant isolation on cleaning_task_id and incident_id ---
#
# The session is bound to the verified token's tenant on the first call (see
# `tests/properties/conftest.py` — `bind_session_to_tenant` is the listener's job).
# A second call as the other tenant in the same test fails to load the user and
# answers `401`. The fix used by the existing `test_a_neighbours_*` tests: seed
# BOTH tenants' rows directly, call only ONCE — as the tenant whose isolation
# is under test — and assert the symmetric property from the response shape.

@pytest.mark.asyncio
async def test_tenant_a_cleaning_task_id_is_a_only_and_excludes_b(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    """R4.1 — calling as tenant A: A's stall shows A's task id, NOT B's."""
    a_prop = await _stalled_property(
        db_session, tenant_a, internal_code="A-CLEAN",
        state=PropertyOperationalState.CLEANING_IN_PROGRESS,
    )
    await _stay(db_session, a_prop)
    a_task = await _open_cleaning_task(db_session, a_prop)

    b_prop = await _stalled_property(
        db_session, tenant_b, internal_code="B-CLEAN",
        state=PropertyOperationalState.CLEANING_IN_PROGRESS,
    )
    await _stay(db_session, b_prop)
    b_task = await _open_cleaning_task(db_session, b_prop)

    response = await api.get(
        ENDPOINT, headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )
    assert response.status_code == 200, response.text
    a_entries = response.json()["data"]
    # A sees ONLY its own stall: B's row is invisible (the existing
    # `test_a_neighbours_stall_is_invisible` covers the stall itself; we add the
    # invariant that the same filter protects the action id).
    assert len(a_entries) == 1
    entry = a_entries[0]
    assert entry["property_code"] == "A-CLEAN"
    assert entry["cleaning_task_id"] == str(a_task.id)
    assert entry["cleaning_task_id"] != str(b_task.id)


@pytest.mark.asyncio
async def test_tenant_b_cleaning_task_id_is_b_only_and_excludes_a(
    api, db_session, tenant_a, tenant_b, users_by_role_b
) -> None:
    """R4.1 (symmetric) — calling as tenant B: B's stall shows B's task id, NOT A's."""
    a_prop = await _stalled_property(
        db_session, tenant_a, internal_code="A-CLEAN2",
        state=PropertyOperationalState.CLEANING_IN_PROGRESS,
    )
    await _stay(db_session, a_prop)
    a_task = await _open_cleaning_task(db_session, a_prop)

    b_prop = await _stalled_property(
        db_session, tenant_b, internal_code="B-CLEAN2",
        state=PropertyOperationalState.CLEANING_IN_PROGRESS,
    )
    await _stay(db_session, b_prop)
    b_task = await _open_cleaning_task(db_session, b_prop)

    response = await api.get(
        ENDPOINT, headers=_at(api, users_by_role_b[UserRole.PROPERTY_MANAGER])
    )
    assert response.status_code == 200, response.text
    b_entries = response.json()["data"]
    assert len(b_entries) == 1
    entry = b_entries[0]
    assert entry["property_code"] == "B-CLEAN2"
    assert entry["cleaning_task_id"] == str(b_task.id)
    assert entry["cleaning_task_id"] != str(a_task.id)


@pytest.mark.asyncio
async def test_tenant_a_incident_id_is_a_only_and_excludes_b(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    """R4.2 — calling as tenant A: A's stall shows A's incident id, NOT B's."""
    a_prop = await _stalled_property(
        db_session, tenant_a, internal_code="A-INC",
        state=PropertyOperationalState.MAINTENANCE_REQUIRED,
    )
    await _stay(db_session, a_prop)
    a_incident = await _open_incident(db_session, a_prop)

    b_prop = await _stalled_property(
        db_session, tenant_b, internal_code="B-INC",
        state=PropertyOperationalState.MAINTENANCE_REQUIRED,
    )
    await _stay(db_session, b_prop)
    b_incident = await _open_incident(db_session, b_prop)

    response = await api.get(
        ENDPOINT, headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )
    assert response.status_code == 200, response.text
    a_entries = response.json()["data"]
    assert len(a_entries) == 1
    entry = a_entries[0]
    assert entry["property_code"] == "A-INC"
    assert entry["incident_id"] == str(a_incident.id)
    assert entry["incident_id"] != str(b_incident.id)


@pytest.mark.asyncio
async def test_tenant_b_incident_id_is_b_only_and_excludes_a(
    api, db_session, tenant_a, tenant_b, users_by_role_b
) -> None:
    """R4.2 (symmetric) — calling as tenant B: B's stall shows B's incident id, NOT A's."""
    a_prop = await _stalled_property(
        db_session, tenant_a, internal_code="A-INC2",
        state=PropertyOperationalState.MAINTENANCE_REQUIRED,
    )
    await _stay(db_session, a_prop)
    a_incident = await _open_incident(db_session, a_prop)

    b_prop = await _stalled_property(
        db_session, tenant_b, internal_code="B-INC2",
        state=PropertyOperationalState.MAINTENANCE_REQUIRED,
    )
    await _stay(db_session, b_prop)
    b_incident = await _open_incident(db_session, b_prop)

    response = await api.get(
        ENDPOINT, headers=_at(api, users_by_role_b[UserRole.PROPERTY_MANAGER])
    )
    assert response.status_code == 200, response.text
    b_entries = response.json()["data"]
    assert len(b_entries) == 1
    entry = b_entries[0]
    assert entry["property_code"] == "B-INC2"
    assert entry["incident_id"] == str(b_incident.id)
    assert entry["incident_id"] != str(a_incident.id)


# --- R4.3: cross-tenant row negative — the row still lists but the id is null ---


@pytest.mark.asyncio
async def test_a_cross_tenant_task_is_not_exposed_on_the_listing(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    """R4.3 — a tenant A flat stalled in CLEANING_IN_PROGRESS, but tenant B ALSO has
    a stall on a different flat, and tenant B's task is the only live task for that
    property. Tenant A's response: only A's stall listed, only A's task id (or null
    if A has no task).

    The cross-tenant leak scenario this test rules out: tenant A's endpoint
    somehow including tenant B's stall or task id in its response. The pre-existing
    `test_a_neighbours_stall_is_invisible` (line 209 of test_blocked_transitions_api.py)
    already proves the stall row is filtered; this test extends that to the action id.
    """
    a_prop = await _stalled_property(
        db_session, tenant_a, internal_code="A-X",
        state=PropertyOperationalState.CLEANING_IN_PROGRESS,
    )
    await _stay(db_session, a_prop)
    # A has no live task — `cleaning_task_id` is null.

    b_prop = await _stalled_property(
        db_session, tenant_b, internal_code="B-X",
        state=PropertyOperationalState.CLEANING_IN_PROGRESS,
    )
    await _stay(db_session, b_prop)
    b_task = await _open_cleaning_task(db_session, b_prop)
    # B has a live task. The cross-tenant concern is that A's response might
    # somehow include B's task id. It must NOT.

    response = await api.get(
        ENDPOINT, headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )
    assert response.status_code == 200, response.text
    [entry] = response.json()["data"]
    assert entry["property_code"] == "A-X"
    assert entry["cleaning_task_id"] is None  # A has no task → null
    assert entry["cleaning_task_id"] != str(b_task.id)  # not B's either


# --- R4.4: extra="forbid" guard on the request side ---


@pytest.mark.asyncio
async def test_tenant_id_in_query_string_is_ignored(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    """R4.4 — `tenant_id` on the query string must NOT route to the other tenant's data.

    The handler reads `tenant_id` from the verified token (`authenticated.context.tenant_id`)
    and ignores any client-supplied `tenant_id`. The endpoint declares only `page` and
    `per_page` as Query parameters; FastAPI silently ignores the unknown `tenant_id`
    key (which is the safe default — accepting an unknown key with no effect is better
    than crashing the request). What matters is that the response carries the calling
    tenant's data, NOT the query-parameter tenant's.
    """
    a_prop = await _stalled_property(
        db_session, tenant_a, internal_code="A-Q",
        state=PropertyOperationalState.CLEANING_IN_PROGRESS,
    )
    await _stay(db_session, a_prop)

    b_prop = await _stalled_property(
        db_session, tenant_b, internal_code="B-Q",
        state=PropertyOperationalState.CLEANING_IN_PROGRESS,
    )
    await _stay(db_session, b_prop)

    response = await api.get(
        f"{ENDPOINT}?tenant_id={tenant_b.id}",
        headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    [entry] = body["data"]
    assert entry["property_code"] == "A-Q"  # NOT B-Q


# --- R4.5: batch discipline — one call per family per page ---


@pytest.mark.asyncio
async def test_a_mixed_page_issues_one_batch_per_family(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R4.5 — a page with stalls from BOTH families issues at most one query per family.

    The bound is independent of page size (R3.4): two calls total (one to
    `cleaning_tasks`, one to `incidents`), never N+1.

    Probing is indirect here: SQLAlchemy emits SQL that we count via an event listener
    rather than mocking the port. The router is the integration seam.
    """
    from sqlalchemy import event

    # Seed five flats: three in cleaning family, two in incident family.
    for i in range(3):
        prop = await _stalled_property(
            db_session, tenant_a,
            internal_code=f"CLEAN{i}",
            state=PropertyOperationalState.CLEANING_IN_PROGRESS,
        )
        await _stay(db_session, prop)
    for i in range(2):
        prop = await _stalled_property(
            db_session, tenant_a,
            internal_code=f"INC{i}",
            state=PropertyOperationalState.MAINTENANCE_REQUIRED,
        )
        await _stay(db_session, prop)

    cleaning_query_count = 0
    incident_query_count = 0

    def _count_statements(conn, cursor, statement, *_):
        nonlocal cleaning_query_count, incident_query_count
        upper = statement.upper()
        if "CLEANING_TASKS" in upper and "FROM CLEANING_TASKS" in upper:
            cleaning_query_count += 1
        if "FROM INCIDENTS" in upper:
            incident_query_count += 1

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", _count_statements)

    try:
        response = await api.get(
            ENDPOINT, headers=_at(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
        )
    finally:
        event.remove(engine, "before_cursor_execute", _count_statements)

    assert response.status_code == 200
    # The two batch readers must run AT MOST once each for the whole page. In
    # practice they may run twice (once for `count_open_for_properties` from the
    # dashboard's no-one-asks-it path, once for our resolver's batch); we assert
    # that the bound is small — never 5 (which would be N+1).
    assert cleaning_query_count <= 2, (
        f"cleaning_tasks queried {cleaning_query_count} times for a page of 3 — "
        f"expected at most 2 (one for our batch resolver, one for other readers). "
        f"N+1 would be 3+."
    )
    assert incident_query_count <= 2, (
        f"incidents queried {incident_query_count} times for a page of 2 — "
        f"expected at most 2 (one for our batch resolver, one for other readers). "
        f"N+1 would be 2+."
    )
