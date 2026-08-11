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

import pytest

from app.maintenance.domain.entities import OPEN_INCIDENT_STATUSES
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    OwnerApprovalRelatedType,
    OwnerApprovalStatus,
)
from app.maintenance.domain.value_objects import IncidentSummary, OwnerApprovalSummary
from app.maintenance.infrastructure.models import IncidentModel, OwnerApprovalModel
from app.maintenance.infrastructure.repositories import (
    SqlAlchemyIncidentReader,
    SqlAlchemyOwnerApprovalReader,
)
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
