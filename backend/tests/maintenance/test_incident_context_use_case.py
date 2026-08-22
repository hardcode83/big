"""`GetIncidentContextUseCase` over the database (R1.1-R1.5, R4.4, R4.6; design D2, D9).

Integration and not unit-with-fakes, for the reason `tests/maintenance/conftest.py` gives about
this module in general and for one that is specific here: D2's whole argument is that composing
two tenant-scoped `get`s is **stricter** than a `JOIN`, because the database accepts an incident
of tenant A pointing at a property of tenant B and the composition turns that row into a `404`.
A fake repository would return whatever the test told it to and would agree with a use case that
had got the scoping wrong.
"""

import logging
import uuid

import pytest

from app.auth.domain.enums import UserRole
from app.maintenance.application.use_cases import (
    GetIncidentContextUseCase,
    IncidentActor,
)
from app.maintenance.domain.enums import IncidentStatus
from app.maintenance.domain.exceptions import IncidentNotFoundError
from app.maintenance.infrastructure.models import IncidentModel
from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.tenants.infrastructure.models import TenantModel
from tests.maintenance.conftest import (  # noqa: F401
    NOW,
    flow,
    make_incident,
    world,
)
from tests.sql_counter import count_statements

pytestmark = pytest.mark.asyncio

ACCESS_NOTES = "El código del portal es 4821 y la llave está en la caja de la entrada."
ASSIGNMENT_NOTE = "Sube por la escalera, el ascensor está averiado."


def _use_case(db_session) -> GetIncidentContextUseCase:
    return GetIncidentContextUseCase(
        incidents=SqlAlchemyIncidentRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
    )


def _technician(world) -> IncidentActor:
    return IncidentActor(user_id=world.technician.id, role=UserRole.TECHNICIAN)


def _manager(world) -> IncidentActor:
    return IncidentActor(user_id=world.manager.id, role=UserRole.PROPERTY_MANAGER)


def _owner(world) -> IncidentActor:
    return IncidentActor(user_id=world.owner.id, role=UserRole.TENANT_OWNER)


async def _fill_property(db_session, world) -> None:
    """The `world` property carries only a name and an internal code, so the address fields
    would all be `None` and the composition would look right while carrying nothing."""
    prop = await db_session.get(PropertyModel, world.property.id)
    prop.address_line1 = "Calle de Redes 11"
    prop.address_line2 = "3º B"
    prop.city = "Madrid"
    prop.province = "Madrid"
    prop.postal_code = "28004"
    prop.country = "ES"
    prop.timezone = "Europe/Madrid"
    prop.access_notes = ACCESS_NOTES
    await db_session.flush()


async def _assigned_incident(flow, world, db_session, *, note: str | None = ASSIGNMENT_NOTE):
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    await flow.assign.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        technician_id=world.technician.id,
        actor=_manager(world),
        now=NOW,
        assignment_note=note,
    )
    return incident


async def test_the_eleven_fields_are_composed_from_the_two_rows(
    flow, world, db_session
) -> None:
    """R1.1, R1.2, R2.1, R3.3 — ten fields from the property, one from the incident."""
    await _fill_property(db_session, world)
    incident = await _assigned_incident(flow, world, db_session)

    context = await _use_case(db_session).execute(
        tenant_id=world.tenant.id, incident_id=incident.id, actor=_technician(world)
    )

    assert context.property_name == "Redes 11"
    assert context.property_internal_code == "REDES11"
    assert context.address_line1 == "Calle de Redes 11"
    assert context.address_line2 == "3º B"
    assert context.city == "Madrid"
    assert context.province == "Madrid"
    assert context.postal_code == "28004"
    assert context.country == "ES"
    assert context.timezone == "Europe/Madrid"
    assert context.access_notes == ACCESS_NOTES
    assert context.assignment_note == ASSIGNMENT_NOTE


async def test_an_unfilled_column_is_none_and_not_an_empty_string(
    flow, world, db_session
) -> None:
    """R1.3 at this layer. The API test proves the key survives serialisation; this proves the
    use case does not invent a value for a column nobody filled in."""
    incident = await _assigned_incident(flow, world, db_session, note=None)

    context = await _use_case(db_session).execute(
        tenant_id=world.tenant.id, incident_id=incident.id, actor=_technician(world)
    )

    assert context.address_line1 is None
    assert context.city is None
    assert context.access_notes is None
    assert context.assignment_note is None


async def test_a_dangling_property_is_a_not_found_and_never_a_partial_answer(
    flow, world, db_session, caplog
) -> None:
    """R1.5, R4.4, design D9 — the asymmetry with `cleaner-task-context`, driven.

    An incident of tenant A pointing at a property of tenant B is a row the database accepts:
    `incidents.property_id` is a plain foreign key to `properties.id`, not composite with
    `tenant_id`. The property feeds ten of the eleven fields, so this **must not** degrade to a
    partial context the way a dangling reservation degrades in `cleaning`.

    The `warning` is asserted too: a crossed pointer is an anomaly a person has to see, and
    nothing else in the flow would ever mention it.
    """
    neighbour = TenantModel(name="TenantB", billing_email="b@example.com")
    db_session.add(neighbour)
    await db_session.flush()
    theirs = PropertyModel(
        tenant_id=neighbour.id, name="Otra", internal_code="OTRA", access_notes="secreto"
    )
    db_session.add(theirs)
    await db_session.flush()

    incident = await _assigned_incident(flow, world, db_session)
    stored = await db_session.get(IncidentModel, incident.id)
    stored.property_id = theirs.id
    await db_session.flush()
    db_session.expunge_all()

    with caplog.at_level(logging.WARNING):
        with pytest.raises(IncidentNotFoundError):
            await _use_case(db_session).execute(
                tenant_id=world.tenant.id,
                incident_id=incident.id,
                actor=_technician(world),
            )

    warnings = [
        record
        for record in caplog.records
        if record.message == "maintenance.incident_context_property_unresolved"
    ]
    assert len(warnings) == 1
    assert warnings[0].tenant_id == str(world.tenant.id)
    assert warnings[0].incident_id == str(incident.id)
    assert warnings[0].property_id == str(theirs.id)


async def test_a_technician_who_is_not_the_assignee_gets_the_same_not_found(
    flow, world, db_session
) -> None:
    """R4.2, R4.4 — the row-level rule, reached through this use case."""
    incident = await _assigned_incident(flow, world, db_session)
    intruder = IncidentActor(
        user_id=world.other_technician.id, role=UserRole.TECHNICIAN
    )

    with pytest.raises(IncidentNotFoundError):
        await _use_case(db_session).execute(
            tenant_id=world.tenant.id, incident_id=incident.id, actor=intruder
        )


async def test_an_unknown_incident_and_another_tenants_incident_are_the_same_refusal(
    flow, world, db_session
) -> None:
    """R4.4 — four cases, one exception, one message. The fourth is the dangling property
    above; these are the other two beyond the unassigned technician."""
    incident = await _assigned_incident(flow, world, db_session)
    neighbour = TenantModel(name="TenantB", billing_email="b@example.com")
    db_session.add(neighbour)
    await db_session.flush()

    with pytest.raises(IncidentNotFoundError) as unknown:
        await _use_case(db_session).execute(
            tenant_id=world.tenant.id,
            incident_id=uuid.uuid4(),
            actor=_technician(world),
        )
    with pytest.raises(IncidentNotFoundError) as cross_tenant:
        await _use_case(db_session).execute(
            tenant_id=neighbour.id, incident_id=incident.id, actor=_technician(world)
        )

    assert str(unknown.value) == str(cross_tenant.value)


async def test_the_incident_level_tenant_filter_is_load_bearing_on_its_own(
    flow, world, db_session
) -> None:
    """R4.6 — a crossing that **no other clause can mask**, which is why it is contrived.

    The obvious cross-tenant test does not prove what it looks like it proves. Two other
    clauses stand in front of the incident's own `tenant_id` filter and each will refuse first:

    * If the incident points at a property of *its* tenant, `properties.get(caller_tenant, ...)`
      resolves to `None` and raises through the **property** branch — so deleting the filter
      from `IncidentRepository.get` changes nothing observable.
    * If the caller is a `TECHNICIAN`, `restrict_to_technician_id` does not match an incident
      nobody assigned to them, so the **row-scope** clause raises first — same masking, second
      mechanism.

    So the only shape in which the incident-level tenant filter is the *sole* thing refusing is
    this one: an incident belonging to the neighbour, pointing at **our** property, read by
    **our manager** (whose `restrict_to_technician_id` is `None`). Delete the filter and this
    returns a full, populated context for a row of another tenant. Raised by the QA panel of
    sections 4-5, which found the straightforward version masked — and the test it proposed
    instead is masked too, by the second bullet above.
    """
    await _fill_property(db_session, world)
    neighbour = TenantModel(name="TenantB", billing_email="b@example.com")
    db_session.add(neighbour)
    await db_session.flush()

    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    stored = await db_session.get(IncidentModel, incident.id)
    stored.tenant_id = neighbour.id
    await db_session.flush()
    db_session.expunge_all()

    with pytest.raises(IncidentNotFoundError):
        await _use_case(db_session).execute(
            tenant_id=world.tenant.id,
            incident_id=incident.id,
            actor=_manager(world),
        )


@pytest.mark.parametrize("role", ["manager", "owner"])
async def test_a_manager_and_an_owner_reach_any_incident_of_their_tenant(
    flow, world, db_session, role: str
) -> None:
    """R4.3 — neither is narrowed, and the incident is assigned to somebody else, which is the
    only shape in which the absence of the restriction is visible."""
    await _fill_property(db_session, world)
    incident = await _assigned_incident(flow, world, db_session)
    actor = _manager(world) if role == "manager" else _owner(world)

    context = await _use_case(db_session).execute(
        tenant_id=world.tenant.id, incident_id=incident.id, actor=actor
    )

    assert context.access_notes == ACCESS_NOTES


async def test_the_projection_costs_two_statements(flow, world, db_session) -> None:
    """D2's declared cost, counted rather than claimed.

    Two `SELECT`s: the incident and its property. A third would mean somebody added a
    repository — a reservation, a user, a timeline read — and R5.3's "ningún campo de reserva"
    is enforced partly by there being no statement that could produce one.
    """
    await _fill_property(db_session, world)
    incident = await _assigned_incident(flow, world, db_session)
    db_session.expunge_all()
    use_case = _use_case(db_session)

    with count_statements(db_session.bind) as log:
        await use_case.execute(
            tenant_id=world.tenant.id, incident_id=incident.id, actor=_technician(world)
        )

    selects = log.matching("SELECT")
    assert len(selects) == 2, selects
    assert not log.matching("FROM reservations")
    assert not log.matching("FROM users")


async def test_a_refused_read_costs_one_statement_at_most(flow, world, db_session) -> None:
    """The `404` paths stop early: an incident that does not load never reaches the property."""
    use_case = _use_case(db_session)

    with count_statements(db_session.bind) as log:
        with pytest.raises(IncidentNotFoundError):
            await use_case.execute(
                tenant_id=world.tenant.id,
                incident_id=uuid.uuid4(),
                actor=_technician(world),
            )

    assert len(log.matching("SELECT")) <= 1
    assert not log.matching("FROM properties")
