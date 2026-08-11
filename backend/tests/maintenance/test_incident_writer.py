"""`SqlAlchemyIncidentRepository`, against real Postgres (R5.1, R5.4, R5.5; design D15).

Separate from `test_repositories.py`, which covers the **read** ports `dashboard-api` added to
this module. Two changes own the two halves of `maintenance`'s persistence and each brings its own
helpers; merging the files would have meant reconciling two sets of fixtures for no gain, and the
split says out loud which change owns which contract.

Integration rather than unit, because what is under test is what a fake cannot show: that the row
a guest's report produces is one the classification flow — and the dashboard reader next door —
cannot tell apart from any other in `OPEN`, which is a statement about the **DDL's** defaults and
not about the entity's.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import bind_session_to_tenant
from app.core.tenancy import CrossTenantWriteError
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token
from app.maintenance.domain.entities import Incident
from app.maintenance.domain.enums import IncidentSource, IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel
from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository
from app.properties.infrastructure.models import PropertyModel
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantModel

CHECK_IN = date(2026, 9, 1)
NOW = datetime(2026, 9, 2, 10, 30, tzinfo=UTC)


async def _stay(db_session, name: str):
    tenant = TenantModel(name=name, billing_email=f"{name}@example.com")
    db_session.add(tenant)
    await db_session.flush()

    prop = PropertyModel(
        tenant_id=tenant.id,
        name=f"Property {name}",
        internal_code=f"CODE-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(prop)
    await db_session.flush()

    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="DIRECT",
        status="CONFIRMED",
        check_in_date=CHECK_IN,
        check_out_date=CHECK_IN + timedelta(days=2),
        nights=2,
    )
    db_session.add(reservation)
    await db_session.flush()
    return tenant, prop, reservation


def _guest_incident(tenant, prop, reservation, token_hash: str) -> Incident:
    """What `ReportGuestIncidentUseCase` builds: the five fields it sets, and no more."""
    return Incident(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=prop.id,
        source=IncidentSource.GUEST,
        title="The boiler makes a loud noise",
        description="It started last night and wakes us up.",
        created_at=NOW,
        updated_at=NOW,
        reservation_id=reservation.id,
        reported_by_guest_token=token_hash,
    )


@pytest.mark.asyncio
async def test_it_persists_the_report_with_the_digest_and_the_stay(db_session) -> None:
    tenant, prop, reservation = await _stay(db_session, "roundtrip")
    token = generate_guest_token()
    repository = SqlAlchemyIncidentRepository(db_session)

    incident = _guest_incident(tenant, prop, reservation, hash_guest_token(token))
    await repository.add(tenant.id, incident)
    await db_session.commit()

    stored = (
        await db_session.execute(select(IncidentModel).where(IncidentModel.id == incident.id))
    ).scalar_one()
    assert stored.source is IncidentSource.GUEST
    assert stored.status is IncidentStatus.OPEN
    assert stored.property_id == prop.id
    assert stored.reservation_id == reservation.id
    assert stored.reported_by_user_id is None
    # The digest, and — the half that matters — not the value it digests.
    assert stored.reported_by_guest_token == hash_guest_token(token)
    assert stored.reported_by_guest_token != token
    assert token not in (stored.title + stored.description)


@pytest.mark.asyncio
async def test_the_row_is_indistinguishable_from_any_other_open_incident(db_session) -> None:
    """R5.4, checked against the **DDL** rather than against the entity's defaults.

    The four columns the classification flow owns must come back at the values any other
    `OPEN` incident would carry. Asserting they equal `Incident`'s own defaults would be
    circular — the entity is what the repository was handed — so the expectation is read from
    the columns' `server_default`, which is what a row created by anybody else gets.

    That is also what stops the two drifting: if a later change moves a column's default,
    this fails until the entity follows, instead of quietly making a guest's incident the odd
    one out for the classifier.
    """
    tenant, prop, reservation = await _stay(db_session, "indistinguishable")
    repository = SqlAlchemyIncidentRepository(db_session)

    incident = _guest_incident(tenant, prop, reservation, hash_guest_token("h"))
    await repository.add(tenant.id, incident)
    await db_session.commit()

    stored = (
        await db_session.execute(select(IncidentModel).where(IncidentModel.id == incident.id))
    ).scalar_one()
    columns = IncidentModel.__table__.columns
    assert stored.category.value == columns["category"].server_default.arg
    assert stored.severity.value == columns["severity"].server_default.arg
    assert stored.status.value == columns["status"].server_default.arg
    # No server default: nullable columns the classifier fills in later.
    assert columns["ai_summary"].server_default is None
    assert columns["ai_classification"].server_default is None
    assert stored.ai_summary is None
    assert stored.ai_classification is None
    assert stored.assigned_technician_id is None
    assert stored.owner_approval_required is False


@pytest.mark.asyncio
async def test_it_refuses_to_write_an_incident_of_another_tenant(db_session) -> None:
    """The session's global filter does not cover INSERTs, so this guard is the only one."""
    tenant_a, prop_a, reservation_a = await _stay(db_session, "guard-a")
    tenant_b, _, _ = await _stay(db_session, "guard-b")
    repository = SqlAlchemyIncidentRepository(db_session)

    incident = _guest_incident(tenant_a, prop_a, reservation_a, hash_guest_token("x"))
    with pytest.raises(CrossTenantWriteError):
        await repository.add(tenant_b.id, incident)


@pytest.mark.asyncio
async def test_it_never_commits(db_session) -> None:
    """R6.2 needs the incident and its audit row to land together, which only holds if the
    adapter leaves the transaction open for the use case to end."""
    tenant, prop, reservation = await _stay(db_session, "no-commit")
    repository = SqlAlchemyIncidentRepository(db_session)

    incident = _guest_incident(tenant, prop, reservation, hash_guest_token("y"))
    await repository.add(tenant.id, incident)
    await db_session.rollback()

    assert (
        await db_session.execute(select(IncidentModel).where(IncidentModel.id == incident.id))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_a_marked_session_only_sees_its_own_tenants_incidents(db_session) -> None:
    """Rule 1 of `steering/security.md` — the module's own isolation test.

    `incidents` is written on a session the authoriser has already bound to the tenant it
    resolved from the token (D4 step 4), so the global filter must cover this table like any
    other.
    """
    tenant_a, prop_a, reservation_a = await _stay(db_session, "marked-a")
    tenant_b, prop_b, reservation_b = await _stay(db_session, "marked-b")
    repository = SqlAlchemyIncidentRepository(db_session)
    await repository.add(
        tenant_a.id, _guest_incident(tenant_a, prop_a, reservation_a, hash_guest_token("a"))
    )
    await repository.add(
        tenant_b.id, _guest_incident(tenant_b, prop_b, reservation_b, hash_guest_token("b"))
    )
    await db_session.flush()
    db_session.expunge_all()

    bind_session_to_tenant(db_session, tenant_a.id)

    visible = (await db_session.execute(select(IncidentModel))).scalars().all()

    assert [row.tenant_id for row in visible] == [tenant_a.id]
