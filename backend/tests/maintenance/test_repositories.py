"""The **read** ports of `maintenance` (`dashboard-api` R1, R2, task 4.2).

Read-only by construction: `IncidentReader` and `OwnerApprovalReader` declare no writer, so
there is none to test here. That sentence used to say there was no writer *in the system* and
that `incidents` was empty for every tenant — `guest-portal-api` made both false by giving the
module `IncidentRepository` and a route that fills the table from the guest portal. Its tests
live in `test_incident_writer.py`; what still matters here is unchanged, and is now load-bearing
rather than hypothetical: the counts are right with the table empty **and** right once rows
exist, because rows now do exist.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.infrastructure.models import (
    CleaningChecklistTemplateModel,
    CleaningTaskModel,
)
from app.core.tenancy import CrossTenantWriteError
from app.maintenance.domain.entities import (
    OPEN_INCIDENT_STATUSES,
    Incident,
    OwnerApproval,
)
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)
from app.maintenance.domain.exceptions import MaintenanceValidationError
from app.maintenance.domain.repositories import IncidentFilters
from tests.maintenance.conftest import make_incident
from app.maintenance.domain.value_objects import (
    IncidentClassification,
    IncidentSummary,
    OwnerApprovalSummary,
)
from app.maintenance.infrastructure.models import IncidentModel, OwnerApprovalModel
from app.maintenance.infrastructure.repositories import (
    SqlAlchemyIncidentReader,
    SqlAlchemyIncidentRepository,
    SqlAlchemyLiveCleaningTaskQuery,
    SqlAlchemyOwnerApprovalReader,
    SqlAlchemyOwnerApprovalRepository,
)
from sqlalchemy import text

from app.auth.infrastructure.models import UserModel
from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel
from tests.sql_counter import count_statements

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _property(db_session, tenant: TenantModel, code: str) -> PropertyModel:
    model = PropertyModel(tenant_id=tenant.id, name=code, internal_code=code)
    db_session.add(model)
    await db_session.flush()
    return model


async def _incident(
    db_session,
    tenant: TenantModel,
    prop: PropertyModel,
    *,
    status: IncidentStatus = IncidentStatus.OPEN,
    created_at: datetime = NOW,
) -> IncidentModel:
    model = IncidentModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.GUEST,
        category=IncidentCategory.APPLIANCE,
        severity=IncidentSeverity.HIGH,
        title="Boiler is dead",
        # Free text with something a reporter should never have typed, so the projection
        # tests below are asserting absence of a real value and not of an empty string.
        description="No hot water. My passport number is 12345678Z, call me.",
        ai_summary="Boiler failure, guest inconvenienced",
        reported_by_guest_token="guest-token-abc123",
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )
    db_session.add(model)
    await db_session.flush()
    return model


async def _approval(
    db_session,
    tenant: TenantModel,
    prop: PropertyModel,
    *,
    status: OwnerApprovalStatus = OwnerApprovalStatus.PENDING,
    requested_at: datetime = NOW,
) -> OwnerApprovalModel:
    model = OwnerApprovalModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        related_type=OwnerApprovalRelatedType.INCIDENT,
        related_id=uuid.uuid4(),
        amount=180,
        reason="Replace the boiler",
        status=status,
        requested_at=requested_at,
    )
    db_session.add(model)
    await db_session.flush()
    return model


# --- the open/closed line (ASSUMPTION, R2.3) -------------------------------------------


def test_the_open_statuses_are_every_status_but_the_two_terminal_ones() -> None:
    """Defined by exclusion so a status added later is open until someone decides
    otherwise — the safe direction for a count an operator acts on."""
    assert OPEN_INCIDENT_STATUSES == frozenset(IncidentStatus) - {
        IncidentStatus.RESOLVED,
        IncidentStatus.CANCELLED,
    }
    assert IncidentStatus.WAITING_EXTERNAL_PARTS in OPEN_INCIDENT_STATUSES


# --- count_open_for_properties (R1.7) ---------------------------------------------------


@pytest.mark.asyncio
async def test_the_count_is_empty_when_the_table_is_empty(db_session) -> None:
    """The case of today: `incidents` has no writer until the `maintenance` change."""
    tenant = await _tenant(db_session, "TenantA")
    one = await _property(db_session, tenant, "REDES11")
    two = await _property(db_session, tenant, "PAJARITOS8")

    counts = await SqlAlchemyIncidentReader(db_session).count_open_for_properties(
        tenant.id, [one.id, two.id]
    )

    assert counts == {}


@pytest.mark.asyncio
async def test_an_empty_batch_returns_an_empty_mapping_without_querying(
    db_session, test_engine
) -> None:
    """The name promises "without querying", so the test counts rather than trusting.

    `== {}` alone would also pass for an implementation that emitted `IN ()` and got zero
    rows back — the QA panel of section 4 caught exactly that gap.
    """
    tenant = await _tenant(db_session, "TenantA")

    with count_statements(test_engine) as log:
        counts = await SqlAlchemyIncidentReader(db_session).count_open_for_properties(
            tenant.id, []
        )

    assert counts == {}
    assert log.matching("incidents") == []


@pytest.mark.asyncio
async def test_the_count_reports_open_incidents_per_property(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    one = await _property(db_session, tenant, "REDES11")
    two = await _property(db_session, tenant, "PAJARITOS8")
    quiet = await _property(db_session, tenant, "SILENCIO1")
    await _incident(db_session, tenant, one)
    await _incident(db_session, tenant, one, status=IncidentStatus.IN_PROGRESS)
    await _incident(db_session, tenant, two)

    counts = await SqlAlchemyIncidentReader(db_session).count_open_for_properties(
        tenant.id, [one.id, two.id, quiet.id]
    )

    assert counts == {one.id: 2, two.id: 1}
    assert quiet.id not in counts, "a property with none is absent, not mapped to 0"


@pytest.mark.asyncio
@pytest.mark.parametrize("closed", [IncidentStatus.RESOLVED, IncidentStatus.CANCELLED])
async def test_a_closed_incident_is_not_counted(db_session, closed: IncidentStatus) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    await _incident(db_session, tenant, prop, status=closed)

    counts = await SqlAlchemyIncidentReader(db_session).count_open_for_properties(
        tenant.id, [prop.id]
    )

    assert counts == {}


@pytest.mark.asyncio
async def test_the_count_never_crosses_a_tenant_boundary(db_session) -> None:
    """DoD §28.18."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _property(db_session, tenant_a, "REDES11")
    theirs = await _property(db_session, tenant_b, "THEIRS")
    await _incident(db_session, tenant_a, mine)
    await _incident(db_session, tenant_b, theirs)
    await _incident(db_session, tenant_b, theirs)

    counts = await SqlAlchemyIncidentReader(db_session).count_open_for_properties(
        # Asking for the neighbour's property id explicitly: the tenant decides, not the id.
        tenant_a.id,
        [mine.id, theirs.id],
    )

    assert counts == {mine.id: 1}


# --- list_open_for_property (R2.1) ------------------------------------------------------


@pytest.mark.asyncio
async def test_the_open_list_is_empty_today(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")

    assert (
        await SqlAlchemyIncidentReader(db_session).list_open_for_property(tenant.id, prop.id)
        == []
    )


@pytest.mark.asyncio
async def test_the_open_list_returns_projections_newest_first(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    old = await _incident(db_session, tenant, prop, created_at=NOW - timedelta(days=2))
    new = await _incident(db_session, tenant, prop, created_at=NOW)
    await _incident(db_session, tenant, prop, status=IncidentStatus.RESOLVED)

    found = await SqlAlchemyIncidentReader(db_session).list_open_for_property(
        tenant.id, prop.id
    )

    assert [incident.id for incident in found] == [new.id, old.id]
    assert found[0].category is IncidentCategory.APPLIANCE
    assert found[0].severity is IncidentSeverity.HIGH
    assert found[0].opened_at == NOW


@pytest.mark.asyncio
async def test_the_open_list_never_reads_another_tenants_incidents(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, "THEIRS")
    await _incident(db_session, tenant_b, theirs)

    found = await SqlAlchemyIncidentReader(db_session).list_open_for_property(
        tenant_a.id, theirs.id
    )

    assert found == []


# --- the projections, and what they structurally cannot carry ---------------------------
#
# The security panel of section 4 found these readers returning whole entities. The remedy
# is the `GuestSummary` construction (`app/guests/domain/value_objects.py:24-39`): a field
# that is not on the type cannot be serialised by anything downstream. These tests assert
# the absence rather than trusting it.


def test_the_incident_projection_has_no_free_text_and_no_identifiers() -> None:
    """Rule 11 of `steering/security.md`: free text and free JSON are sinks that "pueden
    acabar transportando un valor sensible sin declararlo en su nombre"."""
    import dataclasses

    fields = {field.name for field in dataclasses.fields(IncidentSummary)}

    assert fields == {"id", "category", "severity", "opened_at"}
    for forbidden in (
        "description",
        "ai_summary",
        "ai_classification",
        "reported_by_guest_token",
        "reported_by_user_id",
        "assigned_technician_id",
        "estimated_cost",
        "approved_cost",
        "final_cost",
        "title",
    ):
        assert forbidden not in fields


def test_the_owner_approval_projection_has_no_free_text() -> None:
    import dataclasses

    fields = {field.name for field in dataclasses.fields(OwnerApprovalSummary)}

    assert fields == {"id", "related_type", "amount", "requested_at"}
    for forbidden in ("reason", "response_notes", "responded_by"):
        assert forbidden not in fields


@pytest.mark.asyncio
async def test_the_incident_reader_never_selects_the_sensitive_columns(
    db_session, test_engine
) -> None:
    """Not just absent from the type — never read out of the database at all.

    **Asserting on the SQL, not on the result**, and the difference is the whole test: the
    QA panel of section 4 probed a version that fetched the whole row and narrowed in
    Python afterwards, and a `repr(found)` assertion passed it happily — because the
    projection had already dropped the fields by the time anything was inspected. Only the
    statement text can tell the two implementations apart, which is what makes the
    "never read at all" claim in the adapter's docstring verifiable rather than aspirational.
    """
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    await _incident(db_session, tenant, prop)

    with count_statements(test_engine) as log:
        found = await SqlAlchemyIncidentReader(db_session).list_open_for_property(
            tenant.id, prop.id
        )

    assert len(found) == 1
    statements = log.matching("from incidents")
    assert len(statements) == 1
    selected = statements[0].lower()
    for column in (
        "description",
        "ai_summary",
        "ai_classification",
        "reported_by_guest_token",
        "reported_by_user_id",
        "assigned_technician_id",
        "estimated_cost",
        "approved_cost",
        "final_cost",
        "incidents.title",
    ):
        assert column not in selected, f"the query still reads {column}"


@pytest.mark.asyncio
async def test_the_approval_reader_never_selects_the_sensitive_columns(
    db_session, test_engine
) -> None:
    """The sibling of the test above — the QA panel noted this reader had no round-trip
    coverage at all, so a regression to a whole-row select was caught by nothing."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    await _approval(db_session, tenant, prop)

    with count_statements(test_engine) as log:
        found = await SqlAlchemyOwnerApprovalReader(db_session).list_pending_for_property(
            tenant.id, prop.id
        )

    assert len(found) == 1
    statements = log.matching("from owner_approvals")
    assert len(statements) == 1
    selected = statements[0].lower()
    for column in ("reason", "response_notes", "responded_by", "responded_at"):
        assert column not in selected, f"the query still reads {column}"


# --- owner approvals (PRD §9.2) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_pending_approvals_are_empty_today(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")

    assert (
        await SqlAlchemyOwnerApprovalReader(db_session).list_pending_for_property(
            tenant.id, prop.id
        )
        == []
    )


@pytest.mark.asyncio
async def test_the_pending_approvals_come_back_oldest_request_first(db_session) -> None:
    """A to-do list, not a feed: the one that has waited longest matters most."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    newer = await _approval(db_session, tenant, prop, requested_at=NOW)
    older = await _approval(db_session, tenant, prop, requested_at=NOW - timedelta(days=3))

    found = await SqlAlchemyOwnerApprovalReader(db_session).list_pending_for_property(
        tenant.id, prop.id
    )

    assert [approval.id for approval in found] == [older.id, newer.id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answered",
    [OwnerApprovalStatus.APPROVED, OwnerApprovalStatus.REJECTED, OwnerApprovalStatus.EXPIRED],
)
async def test_an_answered_approval_is_not_pending(
    db_session, answered: OwnerApprovalStatus
) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    await _approval(db_session, tenant, prop, status=answered)

    found = await SqlAlchemyOwnerApprovalReader(db_session).list_pending_for_property(
        tenant.id, prop.id
    )

    assert found == []


@pytest.mark.asyncio
async def test_the_pending_approvals_never_cross_a_tenant_boundary(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, "THEIRS")
    await _approval(db_session, tenant_b, theirs)

    found = await SqlAlchemyOwnerApprovalReader(db_session).list_pending_for_property(
        tenant_a.id, theirs.id
    )

    assert found == []


# --- The ports `maintenance` adds (R2, R4, R5; design D7, D11, D15) ---------------------
#
# These run on `db_session`, which is **not** bound to a tenant. That is deliberate, and it
# is what makes the isolation tests at the end of this file able to fail at all: on a marked
# session the global loader of `app/core/db.py` filters every statement, so a repository that
# forgot its own `WHERE tenant_id` would still return nothing from a neighbour and the test
# would pass while the code was wrong (design D15).


def _reader(db_session) -> SqlAlchemyIncidentReader:
    return SqlAlchemyIncidentReader(db_session)


def _incidents(db_session) -> SqlAlchemyIncidentRepository:
    return SqlAlchemyIncidentRepository(db_session)


def _approvals(db_session) -> SqlAlchemyOwnerApprovalRepository:
    return SqlAlchemyOwnerApprovalRepository(db_session)


async def _user(db_session, tenant: TenantModel, role: str) -> UserModel:
    """A real row, because `incidents.assigned_technician_id` and
    `owner_approvals.responded_by` are foreign keys into `users`."""
    user = UserModel(
        tenant_id=tenant.id,
        name=f"{role.title()} {uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        password_hash="hash",
        role=role,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _cleaning_task(
    db_session, tenant: TenantModel, prop: PropertyModel, status: CleaningTaskStatus
) -> CleaningTaskModel:
    template = CleaningChecklistTemplateModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=f"Standard {uuid.uuid4().hex[:6]}",
        items=[{"id": "kitchen", "label": "Kitchen", "required": True}],
        required_photos=[],
    )
    db_session.add(template)
    await db_session.flush()
    task = CleaningTaskModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        checklist_template_id=template.id,
        status=status,
        scheduled_start=NOW,
        scheduled_end=NOW + timedelta(hours=2),
    )
    db_session.add(task)
    await db_session.flush()
    return task


@pytest.mark.asyncio
async def test_get_returns_the_incident_as_an_entity(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    row = await _incident(db_session, tenant, prop)

    found = await _incidents(db_session).get(tenant.id, row.id)

    assert found is not None
    assert found.id == row.id
    assert found.status is IncidentStatus.OPEN
    assert found.severity is IncidentSeverity.HIGH
    # The whole entity, unlike the dashboard projections above: this is the surface a
    # technician works from, and the description is what tells them what to bring.
    assert found.description.startswith("No hot water")


@pytest.mark.asyncio
async def test_no_read_path_hydrates_the_reporter_token(db_session) -> None:
    """The digest correlates one guest's stay across properties, and nothing in this flow
    reads it — so it does not leave Postgres. Raised by the security panel of section 5.

    Dropping it is safe and not lossy, which the second half of this test pins: the column
    is not in `_MUTABLE_INCIDENT_COLUMNS`, so hydrating and saving cannot erase what the
    guest portal wrote.
    """
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    row = await _incident(db_session, tenant, prop)
    repository = _incidents(db_session)

    incident = await repository.get(tenant.id, row.id)
    assert incident is not None
    assert incident.reported_by_guest_token is None

    page = await _reader(db_session).list(tenant.id, IncidentFilters(), page=1, per_page=20)
    assert all(item.reported_by_guest_token is None for item in page.items)

    active = await _reader(db_session).list_active_for_property(tenant.id, prop.id)
    assert all(item.reported_by_guest_token is None for item in active)

    incident.set_triage(severity=IncidentSeverity.CRITICAL, now=NOW + timedelta(hours=1))
    await repository.save(tenant.id, incident)
    db_session.expunge_all()

    stored = await db_session.get(IncidentModel, row.id)
    assert stored is not None
    assert stored.reported_by_guest_token == "guest-token-abc123"


@pytest.mark.asyncio
async def test_an_incident_written_by_the_real_writer_is_a_classification_candidate(
    db_session,
) -> None:
    """D3's candidate rule, against a row **the writer produced** and not a fixture.

    This is the test the whole suite was missing, and the gap was not academic: every
    fixture in this file builds `IncidentModel(...)` without naming `ai_classification`, so
    the column default gave them SQL `NULL` and the rule matched. The writer names every
    field explicitly, and SQLAlchemy's JSON types turn an assigned Python `None` into JSON
    `'null'` — which `IS NULL` does not match. The job therefore saw zero candidates for
    every incident a real caller had opened, with the suite fully green. Found by the manual
    end-to-end check of task 10.5.
    """
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    incident = Incident(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.GUEST,
        title="Fuga de agua",
        description="Sale agua por debajo del lavabo.",
        created_at=NOW,
        updated_at=NOW,
    )
    await SqlAlchemyIncidentRepository(db_session).add(tenant.id, incident)

    stored_is_sql_null = await db_session.scalar(
        text("SELECT ai_classification IS NULL FROM incidents WHERE id = :id"),
        {"id": incident.id},
    )
    assert stored_is_sql_null is True

    found = await _reader(db_session).list_pending_classification(tenant.id, limit=10)
    assert [candidate.id for candidate in found] == [incident.id]


@pytest.mark.asyncio
async def test_an_incident_born_outside_a_cleaning_keeps_the_link_null(db_session) -> None:
    """R4.2: the column is optional, and the writer must not turn its absence into anything
    but SQL `NULL` — the failure mode `ai_classification` already had on this same table."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    incident = Incident(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.GUEST,
        title="Fuga de agua",
        description="Sale agua por debajo del lavabo.",
        created_at=NOW,
        updated_at=NOW,
    )
    await SqlAlchemyIncidentRepository(db_session).add(tenant.id, incident)

    stored_is_sql_null = await db_session.scalar(
        text("SELECT cleaning_task_id IS NULL FROM incidents WHERE id = :id"),
        {"id": incident.id},
    )
    assert stored_is_sql_null is True

    found = await SqlAlchemyIncidentRepository(db_session).get(tenant.id, incident.id)
    assert found is not None
    assert found.cleaning_task_id is None


@pytest.mark.asyncio
async def test_an_incident_reported_from_a_cleaning_round_trips_the_link(db_session) -> None:
    """R4.1/R4.3: the link survives write and re-read, which is what makes it usable when a
    manager triages the incident against the photos of that same task."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    task = await _cleaning_task(db_session, tenant, prop, CleaningTaskStatus.IN_PROGRESS)
    incident = Incident(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.CLEANER,
        title="Caldera rota",
        description="No sale agua caliente en el baño.",
        created_at=NOW,
        updated_at=NOW,
        cleaning_task_id=task.id,
    )
    await SqlAlchemyIncidentRepository(db_session).add(tenant.id, incident)

    found = await SqlAlchemyIncidentRepository(db_session).get(tenant.id, incident.id)
    assert found is not None
    assert found.cleaning_task_id == task.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "closed", [IncidentStatus.CANCELLED, IncidentStatus.RESOLVED]
)
async def test_a_closed_incident_is_not_a_candidate_however_unclassified(
    db_session, closed: IncidentStatus
) -> None:
    """The `status = OPEN` half of D3's rule, at the query.

    A manager can cancel a guest-reported incident before the job ever looks at it, so
    "terminal **and** never classified" is a real row and not a contrived one. Without this
    half the job would hand a closed incident to `Incident.classify`, which refuses it — and
    the refusal escapes the use case's `try`, so the whole tenant's tick dies rather than
    that one row. Raised by the QA panel of sections 7-8, which found every other test in
    the pair green under exactly that mutation.
    """
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    await _incident(db_session, tenant, prop, status=closed)

    found = await _reader(db_session).list_pending_classification(tenant.id, limit=10)

    assert found == []


@pytest.mark.asyncio
async def test_a_classified_incident_stops_being_a_candidate(db_session) -> None:
    """The other half of D3: a verdict written — even a low-confidence one — takes the
    incident out of the job's reach, which is what stops it spinning."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    row = await _incident(db_session, tenant, prop)
    row.ai_classification = {"category": "OTHER", "confidence": "0.30"}
    await db_session.flush()

    found = await _reader(db_session).list_pending_classification(tenant.id, limit=10)

    assert found == []


@pytest.mark.asyncio
async def test_get_is_none_for_an_unknown_incident(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")

    assert await _incidents(db_session).get(tenant.id, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_save_persists_what_the_entity_changed(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    row = await _incident(db_session, tenant, prop)
    repository = _incidents(db_session)

    incident = await repository.get(tenant.id, row.id)
    assert incident is not None
    incident.classify(
        IncidentClassification(
            category=IncidentCategory.HVAC,
            severity=IncidentSeverity.CRITICAL,
            summary="Heating problem reported at the property",
            confidence=Decimal("0.95"),
            vocabulary=frozenset({"Heating problem reported at the property"}),
        ),
        confidence_threshold=Decimal("0.75"),
        adapter="RuleBasedIncidentClassifier",
        now=NOW + timedelta(hours=1),
    )
    await repository.save(tenant.id, incident)
    # Detach, so the next `get` builds a fresh entity from the row instead of handing back
    # the instance already in the identity map — `save` writes with an UPDATE statement, and
    # a stale object would make this assert nothing.
    db_session.expunge_all()

    stored = await repository.get(tenant.id, row.id)
    assert stored is not None
    assert stored.status is IncidentStatus.CLASSIFIED
    assert stored.category is IncidentCategory.HVAC
    assert stored.ai_classification is not None
    assert stored.ai_classification["adapter"] == "RuleBasedIncidentClassifier"


@pytest.mark.asyncio
async def test_the_assignment_note_survives_a_save_and_a_reassignment_clears_it(
    db_session,
) -> None:
    """R3.1 — the column round-trips, and `None` reaches the row as SQL `NULL`.

    The second half is the one worth writing: D7 makes `assign` write the note **every**
    time, so an adapter that only persisted it when truthy would silently preserve what the
    manager typed for the previous technician. Asserted through `text()` rather than through
    the entity, because a hydrated `None` looks the same either way — and this is the same
    trap `ai_classification` fell into on this very table.
    """
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    row = await _incident(db_session, tenant, prop, status=IncidentStatus.CLASSIFIED)
    repository = _incidents(db_session)

    incident = await repository.get(tenant.id, row.id)
    assert incident is not None
    incident.assignment_note = "Portal code 4821, key in the entrance box."
    await repository.save(tenant.id, incident)
    db_session.expunge_all()

    stored = await repository.get(tenant.id, row.id)
    assert stored is not None
    assert stored.assignment_note == "Portal code 4821, key in the entrance box."

    stored.assignment_note = None
    await repository.save(tenant.id, stored)
    db_session.expunge_all()

    assert (
        await db_session.scalar(
            text("SELECT assignment_note IS NULL FROM incidents WHERE id = :id"),
            {"id": row.id},
        )
        is True
    )


@pytest.mark.asyncio
async def test_the_eta_and_the_materials_round_trip_and_a_later_save_updates_them(
    db_session,
) -> None:
    """R3.1, R4.1 — the two new columns persist, rehydrate, and can be changed again.

    The second `save` is the half worth writing: `_MUTABLE_INCIDENT_COLUMNS` is an allowlist,
    so a column added to the model and forgotten there would round-trip on the **insert** and
    then silently refuse every later change — which is exactly the shape of the bug that
    allowlist exists to prevent in the other direction.

    `eta_at` is read back through `text()` as well, because a hydrated `None` and a stored
    JSON-ish null look the same from the entity — the trap `ai_classification` fell into on
    this very table.
    """
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    row = await _incident(db_session, tenant, prop, status=IncidentStatus.ACCEPTED)
    repository = _incidents(db_session)
    eta = datetime(2026, 8, 22, 17, 30, tzinfo=UTC)

    incident = await repository.get(tenant.id, row.id)
    assert incident is not None
    incident.eta_at = eta
    incident.materials = "Dos codos de 22 mm y un metro de tubo"
    await repository.save(tenant.id, incident)
    db_session.expunge_all()

    stored = await repository.get(tenant.id, row.id)
    assert stored is not None
    assert stored.eta_at == eta
    assert stored.materials == "Dos codos de 22 mm y un metro de tubo"

    later = eta + timedelta(hours=1)
    stored.eta_at = later
    stored.materials = "Y una junta"
    await repository.save(tenant.id, stored)
    db_session.expunge_all()

    updated = await repository.get(tenant.id, row.id)
    assert updated is not None
    assert updated.eta_at == later
    assert updated.materials == "Y una junta"

    updated.eta_at = None
    await repository.save(tenant.id, updated)
    db_session.expunge_all()

    assert (
        await db_session.scalar(
            text("SELECT eta_at IS NULL FROM incidents WHERE id = :id"),
            {"id": row.id},
        )
        is True
    )


@pytest.mark.asyncio
async def test_save_never_moves_a_row_between_tenants(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    prop = await _property(db_session, tenant_a, "REDES11")
    row = await _incident(db_session, tenant_a, prop)

    incident = await _incidents(db_session).get(tenant_a.id, row.id)
    assert incident is not None

    with pytest.raises(CrossTenantWriteError):
        await _incidents(db_session).save(tenant_b.id, incident)


@pytest.mark.asyncio
async def test_list_active_for_property_excludes_the_terminal_statuses(db_session) -> None:
    """D7: the machine decides from what is **still** open, so a closed one must not count."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    live = await _incident(db_session, tenant, prop, status=IncidentStatus.IN_PROGRESS)
    await _incident(db_session, tenant, prop, status=IncidentStatus.RESOLVED)
    await _incident(db_session, tenant, prop, status=IncidentStatus.CANCELLED)

    found = await _reader(db_session).list_active_for_property(tenant.id, prop.id)

    assert [incident.id for incident in found] == [live.id]


@pytest.mark.asyncio
async def test_list_active_for_property_returns_every_open_one(db_session) -> None:
    """Not only the one being changed — that is the failure D7 names as its main risk."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    first = await _incident(db_session, tenant, prop, created_at=NOW)
    second = await _incident(
        db_session,
        tenant,
        prop,
        status=IncidentStatus.ASSIGNED,
        created_at=NOW + timedelta(hours=1),
    )

    found = await _reader(db_session).list_active_for_property(tenant.id, prop.id)

    assert [incident.id for incident in found] == [first.id, second.id]


@pytest.mark.asyncio
async def test_the_listing_paginates_newest_first(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    oldest = await _incident(db_session, tenant, prop, created_at=NOW)
    middle = await _incident(db_session, tenant, prop, created_at=NOW + timedelta(hours=1))
    newest = await _incident(db_session, tenant, prop, created_at=NOW + timedelta(hours=2))

    first_page = await _reader(db_session).list(
        tenant.id, IncidentFilters(), page=1, per_page=2
    )
    second_page = await _reader(db_session).list(
        tenant.id, IncidentFilters(), page=2, per_page=2
    )

    assert first_page.total == 3
    assert [incident.id for incident in first_page.items] == [newest.id, middle.id]
    assert [incident.id for incident in second_page.items] == [oldest.id]


@pytest.mark.parametrize(
    ("page", "per_page"), [(0, 20), (-1, 20), (1, 0), (1, -5)]
)
@pytest.mark.asyncio
async def test_the_listing_refuses_a_non_positive_page(
    db_session, page: int, per_page: int
) -> None:
    """`offset((page - 1) * per_page)` goes negative and Postgres answers with a
    `DBAPIError`, which reaches a caller as a 500 rather than as the 422 a bad query
    parameter deserves. The route declares `ge=1`; this is what holds for callers that are
    not routes."""
    tenant = await _tenant(db_session, "TenantA")

    with pytest.raises(MaintenanceValidationError):
        await _reader(db_session).list(
            tenant.id, IncidentFilters(), page=page, per_page=per_page
        )


@pytest.mark.asyncio
async def test_the_listing_filters_are_combined_with_and(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    here = await _property(db_session, tenant, "REDES11")
    elsewhere = await _property(db_session, tenant, "PAJARITOS8")
    technician = (await _user(db_session, tenant, "TECHNICIAN")).id
    other_technician = (await _user(db_session, tenant, "TECHNICIAN")).id
    wanted = await _incident(db_session, tenant, here, status=IncidentStatus.ASSIGNED)
    wanted.assigned_technician_id = technician
    # One near-miss per filter, so a condition dropped on the floor shows up as a longer
    # list rather than as the same answer: same technician but another property, same
    # property but another status, same everything but another technician.
    other_property = await _incident(
        db_session, tenant, elsewhere, status=IncidentStatus.ASSIGNED
    )
    other_property.assigned_technician_id = technician
    await _incident(db_session, tenant, here, status=IncidentStatus.OPEN)
    someone_else = await _incident(db_session, tenant, here, status=IncidentStatus.ASSIGNED)
    someone_else.assigned_technician_id = other_technician
    await db_session.flush()

    page = await _reader(db_session).list(
        tenant.id,
        IncidentFilters(
            property_id=here.id,
            status=IncidentStatus.ASSIGNED,
            assigned_technician_id=technician,
        ),
        page=1,
        per_page=20,
    )

    assert [incident.id for incident in page.items] == [wanted.id]
    assert page.total == 1


@pytest.mark.asyncio
async def test_the_severity_filter_narrows_the_listing(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    high = await _incident(db_session, tenant, prop)
    low = await _incident(db_session, tenant, prop)
    low.severity = IncidentSeverity.LOW
    await db_session.flush()

    page = await _reader(db_session).list(
        tenant.id, IncidentFilters(severity=IncidentSeverity.HIGH), page=1, per_page=20
    )

    assert [incident.id for incident in page.items] == [high.id]


@pytest.mark.asyncio
async def test_an_approval_round_trips(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    repository = _approvals(db_session)
    approval = OwnerApproval(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        related_type=OwnerApprovalRelatedType.INCIDENT,
        related_id=uuid.uuid4(),
        amount=Decimal("450.00"),
        reason="Boiler replacement quoted by the technician.",
        requested_at=NOW,
    )

    await repository.add(tenant.id, approval)
    stored = await repository.get(tenant.id, approval.id)

    assert stored is not None
    assert stored.status is OwnerApprovalStatus.PENDING
    assert stored.amount == Decimal("450.00")


@pytest.mark.asyncio
async def test_adding_an_approval_never_crosses_a_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    prop = await _property(db_session, tenant_a, "REDES11")

    with pytest.raises(CrossTenantWriteError):
        await _approvals(db_session).add(
            tenant_b.id,
            OwnerApproval(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                property_id=prop.id,
                related_type=OwnerApprovalRelatedType.INCIDENT,
                related_id=uuid.uuid4(),
                amount=Decimal("450.00"),
                reason="Boiler replacement quoted by the technician.",
                requested_at=NOW,
            ),
        )


@pytest.mark.asyncio
async def test_saving_an_answer_persists_it(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    row = await _approval(db_session, tenant, prop)
    repository = _approvals(db_session)
    responder = (await _user(db_session, tenant, "TENANT_OWNER")).id

    approval = await repository.get(tenant.id, row.id)
    assert approval is not None
    applied = approval.answer(
        status=OwnerApprovalStatus.APPROVED,
        responded_by=responder,
        response_notes="Go ahead.",
        now=NOW + timedelta(hours=1),
    )
    await repository.save(tenant.id, approval)
    # Detach, so the next `get` builds a fresh entity from the row instead of handing back
    # the instance already in the identity map — `save` writes with an UPDATE statement, and
    # a stale object would make this assert nothing.
    db_session.expunge_all()

    stored = await repository.get(tenant.id, row.id)
    assert stored is not None
    assert stored.status is OwnerApprovalStatus.APPROVED
    assert stored.responded_by == responder
    assert applied == Decimal("180.00")


@pytest.mark.asyncio
async def test_saving_an_answer_never_crosses_a_tenant(db_session) -> None:
    """R2.6: "ni responder una de otro tenant" — the write half of it.

    Its siblings `IncidentRepository.save` and `OwnerApprovalRepository.add` each have this
    test; this one did not, and it guards exactly the path R2.6's rejection lands on.
    """
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    prop = await _property(db_session, tenant_a, "REDES11")
    row = await _approval(db_session, tenant_a, prop)

    approval = await _approvals(db_session).get(tenant_a.id, row.id)
    assert approval is not None

    with pytest.raises(CrossTenantWriteError):
        await _approvals(db_session).save(tenant_b.id, approval)


@pytest.mark.asyncio
async def test_find_approved_for_incident_ignores_the_unanswered_and_the_rejected(
    db_session,
) -> None:
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    incident_id = uuid.uuid4()
    approved = await _approval(
        db_session, tenant, prop, status=OwnerApprovalStatus.APPROVED
    )
    approved.related_id = incident_id
    pending = await _approval(db_session, tenant, prop)
    pending.related_id = incident_id
    rejected = await _approval(
        db_session, tenant, prop, status=OwnerApprovalStatus.REJECTED
    )
    rejected.related_id = incident_id
    await db_session.flush()

    found = await _approvals(db_session).find_approved_for_incident(tenant.id, incident_id)

    assert [approval.id for approval in found] == [approved.id]


@pytest.mark.asyncio
async def test_find_approved_for_incident_covers_both_gates(db_session) -> None:
    """D11: the budget gate writes `INCIDENT` and the real-cost gate `MAINTENANCE_COST`, and
    the caller wants either — so `related_type` is not part of the filter."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    incident_id = uuid.uuid4()
    budget = await _approval(db_session, tenant, prop, status=OwnerApprovalStatus.APPROVED)
    budget.related_id = incident_id
    real_cost = await _approval(
        db_session, tenant, prop, status=OwnerApprovalStatus.APPROVED
    )
    real_cost.related_id = incident_id
    real_cost.related_type = OwnerApprovalRelatedType.MAINTENANCE_COST
    await db_session.flush()

    found = await _approvals(db_session).find_approved_for_incident(tenant.id, incident_id)

    assert {approval.id for approval in found} == {budget.id, real_cost.id}


@pytest.mark.asyncio
async def test_the_live_cleaning_task_query_sees_only_the_live_ones(db_session) -> None:
    """D7's third collection. "Live" is `cleaning`'s own `LIVE_STATUSES`, asked through that
    module's adapter rather than restated here."""
    tenant = await _tenant(db_session, "TenantA")
    prop = await _property(db_session, tenant, "REDES11")
    live = await _cleaning_task(db_session, tenant, prop, CleaningTaskStatus.IN_PROGRESS)
    await _cleaning_task(db_session, tenant, prop, CleaningTaskStatus.COMPLETED)

    found = await SqlAlchemyLiveCleaningTaskQuery(db_session).list_live_for_property(
        tenant.id, prop.id
    )

    assert [task.id for task in found] == [live.id]


# --- Tenant isolation of the new ports (R5.4, DoD §28.18, design D15) -------------------
#
# On an **unmarked** session, so a repository that forgot its own `WHERE tenant_id` fails
# here instead of being covered by the global loader criteria of `app/core/db.py`. That is a
# known trap of this codebase: on a marked session the listener filters down to the `select`
# of a single column, and the test cannot fail however wrong the code is.


@pytest.mark.asyncio
async def test_no_new_read_port_crosses_a_tenant_boundary(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, "THEIRS")
    their_incident = await _incident(db_session, tenant_b, theirs)
    their_approval = await _approval(
        db_session, tenant_b, theirs, status=OwnerApprovalStatus.APPROVED
    )
    their_approval.related_id = their_incident.id
    await db_session.flush()

    reader = _reader(db_session)

    assert await _incidents(db_session).get(tenant_a.id, their_incident.id) is None
    assert await _approvals(db_session).get(tenant_a.id, their_approval.id) is None
    assert await reader.list_active_for_property(tenant_a.id, theirs.id) == []
    assert (await reader.list(tenant_a.id, IncidentFilters(), page=1, per_page=20)).items == ()
    assert (
        await _approvals(db_session).find_approved_for_incident(
            tenant_a.id, their_incident.id
        )
        == []
    )


@pytest.mark.asyncio
async def test_the_listing_filters_cannot_reach_across_a_tenant(db_session) -> None:
    """The filters are AND-ed onto the tenant condition, never instead of it: naming the
    neighbour's property explicitly still returns nothing."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, "THEIRS")
    await _incident(db_session, tenant_b, theirs)

    page = await _reader(db_session).list(
        tenant_a.id, IncidentFilters(property_id=theirs.id), page=1, per_page=20
    )

    assert page.items == ()
    assert page.total == 0


@pytest.mark.asyncio
async def test_the_live_cleaning_task_query_does_not_cross_a_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, "THEIRS")
    await _cleaning_task(db_session, tenant_b, theirs, CleaningTaskStatus.IN_PROGRESS)

    found = await SqlAlchemyLiveCleaningTaskQuery(db_session).list_live_for_property(
        tenant_a.id, theirs.id
    )

    assert found == []


# --- incident photos: the adapters (`incident-photos` 4.5/4.6, R1, R3, R4, R6) ---------
#
# Two adapters with opposite contracts, in one place so the contrast is visible:
# `SqlAlchemyIncidentPhotoRepository` demands a tenant on every call, and
# `SqlAlchemyUnscopedIncidentPhotoLocationQuery` refuses to run on a session that has one.


def _incident_photo(incident, uploader, *, stage=None, created_at=None):
    from app.maintenance.domain.entities import IncidentPhoto
    from app.maintenance.domain.enums import IncidentPhotoStage

    photo_id = uuid.uuid4()
    return IncidentPhoto(
        id=photo_id,
        tenant_id=incident.tenant_id,
        incident_id=incident.id,
        uploaded_by=uploader.id,
        stage=stage or IncidentPhotoStage.BEFORE,
        storage_key=(
            f"tenants/{incident.tenant_id}/incidents/{incident.id}/{photo_id}.jpg"
        ),
        created_at=created_at or NOW,
    )


@pytest.mark.asyncio
async def test_incident_photo_add_and_list_round_trip(db_session, world):
    from app.maintenance.infrastructure.repositories import (
        SqlAlchemyIncidentPhotoRepository,
    )

    incident = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    repo = SqlAlchemyIncidentPhotoRepository(db_session)
    photo = _incident_photo(incident, world.technician)

    await repo.add(world.tenant.id, photo)
    listed = await repo.list_for_incident(world.tenant.id, incident.id)

    assert [p.id for p in listed] == [photo.id]
    assert listed[0].storage_key == photo.storage_key
    assert listed[0].tenant_id == world.tenant.id
    assert listed[0].uploaded_by == world.technician.id


@pytest.mark.asyncio
async def test_incident_photos_come_back_oldest_first(db_session, world):
    """R3.1 — the order is the contract, because `BEFORE` then `AFTER` is the story.

    Inserted deliberately out of order so a repository that forgot its `ORDER BY` would have to
    be lucky to pass: without it Postgres is free to return these in physical order, which for
    a fresh page is insertion order — i.e. exactly wrong here.
    """
    from app.maintenance.domain.enums import IncidentPhotoStage
    from app.maintenance.infrastructure.repositories import (
        SqlAlchemyIncidentPhotoRepository,
    )

    incident = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    repo = SqlAlchemyIncidentPhotoRepository(db_session)

    later = _incident_photo(
        incident,
        world.technician,
        stage=IncidentPhotoStage.AFTER,
        created_at=NOW + timedelta(hours=2),
    )
    earlier = _incident_photo(
        incident, world.technician, stage=IncidentPhotoStage.BEFORE, created_at=NOW
    )
    await repo.add(world.tenant.id, later)
    await repo.add(world.tenant.id, earlier)

    listed = await repo.list_for_incident(world.tenant.id, incident.id)

    assert [p.id for p in listed] == [earlier.id, later.id]
    assert [p.stage for p in listed] == [
        IncidentPhotoStage.BEFORE,
        IncidentPhotoStage.AFTER,
    ]


@pytest.mark.asyncio
async def test_several_photos_of_the_same_stage_round_trip(db_session, world):
    """R1.4 at the adapter level: two angles of one fault, both kept."""
    from app.maintenance.domain.enums import IncidentPhotoStage
    from app.maintenance.infrastructure.repositories import (
        SqlAlchemyIncidentPhotoRepository,
    )

    incident = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    repo = SqlAlchemyIncidentPhotoRepository(db_session)
    for offset in (0, 1):
        await repo.add(
            world.tenant.id,
            _incident_photo(
                incident,
                world.technician,
                stage=IncidentPhotoStage.AFTER,
                created_at=NOW + timedelta(minutes=offset),
            ),
        )

    listed = await repo.list_for_incident(world.tenant.id, incident.id)

    assert len(listed) == 2
    assert {p.stage for p in listed} == {IncidentPhotoStage.AFTER}


@pytest.mark.asyncio
async def test_adding_a_photo_for_another_tenant_is_refused(db_session, world):
    """Limit 3 of `app/core/db.py`: the global filter does not cover INSERTs, so the adapter's
    own check is the only thing between a wiring mistake and a row of another tenant."""
    from app.maintenance.infrastructure.repositories import (
        SqlAlchemyIncidentPhotoRepository,
    )

    incident = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    photo = _incident_photo(incident, world.technician)

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyIncidentPhotoRepository(db_session).add(uuid.uuid4(), photo)


@pytest.mark.asyncio
async def test_listing_photos_of_another_tenants_incident_is_empty(db_session, world):
    """The scoping is on the column, with no join needed — design D2's practical payoff."""
    from app.maintenance.infrastructure.repositories import (
        SqlAlchemyIncidentPhotoRepository,
    )

    incident = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    repo = SqlAlchemyIncidentPhotoRepository(db_session)
    await repo.add(world.tenant.id, _incident_photo(incident, world.technician))

    assert await repo.list_for_incident(uuid.uuid4(), incident.id) == []


@pytest.mark.asyncio
async def test_the_unscoped_incident_photo_location_resolves_the_tenant_out_of_the_row(
    db_session, world
):
    """R4.2 — no tenant in, the tenant comes out. One table, no join (design D2/D13)."""
    from app.maintenance.infrastructure.repositories import (
        SqlAlchemyIncidentPhotoRepository,
        SqlAlchemyUnscopedIncidentPhotoLocationQuery,
    )

    incident = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    photo = _incident_photo(incident, world.technician)
    await SqlAlchemyIncidentPhotoRepository(db_session).add(world.tenant.id, photo)
    await db_session.flush()

    located = await SqlAlchemyUnscopedIncidentPhotoLocationQuery(
        db_session
    ).locate_without_tenant_scoping(photo.id)

    assert located is not None
    assert located.tenant_id == world.tenant.id
    assert located.storage_key == photo.storage_key


@pytest.mark.asyncio
async def test_the_unscoped_incident_photo_location_answers_none_for_an_unknown_id(
    db_session, world
):
    """`None`, which the use case turns into the same constant `403` a bad signature gets."""
    from app.maintenance.infrastructure.repositories import (
        SqlAlchemyUnscopedIncidentPhotoLocationQuery,
    )

    located = await SqlAlchemyUnscopedIncidentPhotoLocationQuery(
        db_session
    ).locate_without_tenant_scoping(uuid.uuid4())

    assert located is None


@pytest.mark.asyncio
async def test_the_unscoped_incident_photo_location_refuses_a_marked_session(
    db_session, world
):
    """R6.4/D13: the session contract of this query, executable.

    **Asserting the raise and not the absence of a row is the whole point.** On a marked session
    the global filter of `app/core/db.py` scopes `incident_photos` — it carries `tenant_id`, so
    unlike its cleaning twin it is covered directly — and the query would come back empty for
    every photo of every *other* tenant. Empty is also what an unknown photo id returns, so
    without the guard the wiring mistake would be reported to the browser as a broken signature
    and to us as nothing at all.
    """
    from app.core.db import bind_session_to_tenant
    from app.core.tenancy import TenantMarkedSessionError
    from app.maintenance.infrastructure.repositories import (
        SqlAlchemyIncidentPhotoRepository,
        SqlAlchemyUnscopedIncidentPhotoLocationQuery,
    )

    incident = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    photo = _incident_photo(incident, world.technician)
    await SqlAlchemyIncidentPhotoRepository(db_session).add(world.tenant.id, photo)
    await db_session.flush()
    bind_session_to_tenant(db_session, world.tenant.id)

    with pytest.raises(TenantMarkedSessionError, match="locate_without_tenant_scoping"):
        await SqlAlchemyUnscopedIncidentPhotoLocationQuery(
            db_session
        ).locate_without_tenant_scoping(photo.id)
