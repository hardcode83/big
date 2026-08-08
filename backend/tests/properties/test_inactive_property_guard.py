"""A retired property takes no new reservations, by any of the three routes (design D11).

**Why these live here and not under `tests/reservations/`.** The rule is a consequence of
`properties-crud`: before it, `properties.status` had no writer at all, so no property could
reach `INACTIVE` and the question did not exist. The guard runs inside `reservations` and
`integrations`, but it is this change that owns the reason it exists — and grouping the routes
in one file is what makes it visible that the API is only one of them.

The three routes resolve the property three different ways and none of them looked at `status`:
the manual endpoint by id, the CSV import by `internal_code`, and the PMS sync by
`pms_external_id`. A guard on only the first would have left the other two open. The two batch
routes differ *only* in that resolution step and both hand the result to
`ReservationIngestor._ingest_row`, where the shared guard lives — so exercising the ingestor with
each resolver is what covers them, rather than driving two full pipelines.
"""

import uuid
from datetime import UTC, date, datetime

import pytest

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.ingest import IngestRow, ReservationIngestor
from app.integrations.domain.dtos import ReservationDTO
from app.properties.domain.enums import PropertyStatus
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.application.use_cases import (
    CreateReservationCommand,
    CreateReservationUseCase,
)
from app.reservations.domain.enums import ReservationChannel
from app.reservations.domain.exceptions import InactivePropertyError
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.models import TenantModel
from app.timeline.domain.enums import TimelineActorType
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


async def _tenant(db_session) -> TenantModel:
    tenant = TenantModel(name="Adamar", billing_email="owner@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _user(db_session, tenant) -> UserModel:
    """A REAL user: `timeline_events.actor_user_id` is a foreign key to `users`, so a random
    UUID turns the success case into a constraint violation instead of a test."""
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Manager",
        email=f"manager-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role=UserRole.PROPERTY_MANAGER,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _property(db_session, tenant, *, code: str, status: PropertyStatus) -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant.id,
        name=code.title(),
        internal_code=code,
        pms_external_id=f"PMS-{code}",
        status=status,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


def _create_use_case(db_session) -> CreateReservationUseCase:
    return CreateReservationUseCase(
        reservations=SqlAlchemyReservationRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )


def _command(prop: PropertyModel) -> CreateReservationCommand:
    return CreateReservationCommand(
        property_id=prop.id,
        channel=ReservationChannel.DIRECT,
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 4),
        adults=2,
    )


def _dto(property_external_id: str, external_id: str) -> ReservationDTO:
    return ReservationDTO(
        external_id=external_id,
        channel="DIRECT",
        property_external_id=property_external_id,
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 4),
    )


# --- Route 1: the manual endpoint ---


@pytest.mark.asyncio
async def test_creating_a_reservation_on_a_retired_property_is_refused(db_session) -> None:
    """`409` and not `404`: the caller can already see and re-activate the property, so hiding it
    would turn an actionable conflict into "look elsewhere", and there is no isolation argument
    because the property is inside the acting tenant."""
    tenant = await _tenant(db_session)
    retired = await _property(db_session, tenant, code="REDES11", status=PropertyStatus.INACTIVE)

    with pytest.raises(InactivePropertyError):
        await _create_use_case(db_session).execute(
            tenant_id=tenant.id,
            actor_user_id=uuid.uuid4(),
            command=_command(retired),
            now=NOW,
        )


@pytest.mark.asyncio
async def test_an_active_property_still_accepts_reservations(db_session) -> None:
    """The control case. Without it the test above would pass on a guard that refuses always."""
    tenant = await _tenant(db_session)
    user = await _user(db_session, tenant)
    active = await _property(db_session, tenant, code="PAJARITOS8", status=PropertyStatus.ACTIVE)

    reservation = await _create_use_case(db_session).execute(
        tenant_id=tenant.id,
        actor_user_id=user.id,
        command=_command(active),
        now=NOW,
    )
    assert reservation.property_id == active.id


# --- Routes 2 and 3: the CSV import and the PMS sync, through their shared branch ---


@pytest.mark.parametrize("resolve_by", ["internal_code", "pms_external_id"])
@pytest.mark.asyncio
async def test_the_batch_routes_skip_a_retired_property_without_aborting(
    db_session, resolve_by
) -> None:
    """One retired property must not cost the tenant the rest of the batch.

    Same reasoning R3.4 gives for an unresolvable property: report the row and carry on. The
    parametrisation is the point — `internal_code` is how the CSV import resolves and
    `pms_external_id` is how the sync does, and neither looked at `status` before this change.
    """
    tenant = await _tenant(db_session)
    retired = await _property(db_session, tenant, code="REDES11", status=PropertyStatus.INACTIVE)
    healthy = await _property(
        db_session, tenant, code="PAJARITOS8", status=PropertyStatus.ACTIVE
    )

    properties = SqlAlchemyPropertyRepository(db_session)

    async def resolve(row: ReservationDTO):
        if resolve_by == "internal_code":
            return await properties.find_by_internal_code(tenant.id, row.property_external_id)
        return await properties.find_by_pms_external_id(tenant.id, row.property_external_id)

    reference = "internal_code" if resolve_by == "internal_code" else "pms_external_id"
    retired_ref = retired.internal_code if reference == "internal_code" else retired.pms_external_id
    healthy_ref = healthy.internal_code if reference == "internal_code" else healthy.pms_external_id

    ingestor = ReservationIngestor(
        reservations=SqlAlchemyReservationRepository(db_session),
        guests=SqlAlchemyGuestRepository(db_session),
        timeline=SqlAlchemyTimelineEventRepository(db_session),
    )
    report = await ingestor.ingest(
        tenant_id=tenant.id,
        rows=[
            IngestRow(dto=_dto(retired_ref, "EXT-1"), line=1),
            IngestRow(dto=_dto(healthy_ref, "EXT-2"), line=2),
        ],
        resolve_property=resolve,
        now=NOW,
        actor_type=TimelineActorType.SYSTEM,
        actor_user_id=None,
        source="test",
    )

    # The healthy row still went through: that half is what proves the batch was not aborted.
    assert report.created == 1
    assert report.skipped == 1
    reasons = [error.reason for error in report.errors]
    assert any("retired" in reason for reason in reasons), reasons
    # And NOT the "unknown property" reason: the property exists, it is retired, and a person
    # reading the report has to be able to act on the difference.
    assert not any("Unknown property" in reason for reason in reasons), reasons
