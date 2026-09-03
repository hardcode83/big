"""The two dashboard use cases (`dashboard-api` R1, R2, tasks 6.1-6.2).

Unit tests over in-memory fakes of the ports, as `steering/testing.md` requires of
`application/`. What they pin is composition and **omission** — which blocks come back, and
which do not because the calling role may not read their source (design D10).
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.auth.domain.enums import UserRole
from app.auth.domain.policy import Permission
from app.cleaning.domain.enums import CleaningTaskStatus
from app.core.i18n import Locale
from app.dashboard.application.use_cases import (
    GetDashboardCardsUseCase,
    GetOccupancySeriesUseCase,
    GetPropertyDashboardUseCase,
)
from app.dashboard.domain.occupancy import week_bounds
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus
from app.properties.domain.exceptions import PropertyNotFoundError
from tests.dashboard.doubles import (
    TODAY,
    FakeCleaningRepository,
    FakeExpenseReader,
    FakeGuestRepository,
    FakeIncidentReader,
    FakeOwnerApprovalReader,
    FakePropertyRepository,
    FakePropertyStateTransitionRepository,
    FakeReservationRepository,
    FakeTimelineReader,
    make_approval,
    make_cleaning,
    make_event,
    make_guest,
    make_incident,
    make_property,
    make_reservation,
)

TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()


@pytest.fixture
def world():
    """One tenant, one property, one reservation with a guest, one live cleaning task,
    two open incidents and a last event — enough for every block to be non-empty."""
    prop = make_property(TENANT, state=PropertyOperationalState.AWAITING_CLEANING)
    guest_id = uuid.uuid4()
    reservation = make_reservation(TENANT, prop.id, guest_id=guest_id)
    return {
        "property": prop,
        "guest_id": guest_id,
        "reservation": reservation,
        "properties": FakePropertyRepository({TENANT: [prop]}),
        "reservations": FakeReservationRepository({TENANT: [reservation]}),
        "guests": FakeGuestRepository({guest_id: make_guest(guest_id)}),
        "cleaning": FakeCleaningRepository(
            {TENANT: [make_cleaning(prop.id, CleaningTaskStatus.IN_PROGRESS)]}
        ),
        "incidents": FakeIncidentReader(
            counts={TENANT: {prop.id: 2}},
            open_by_property={prop.id: [make_incident(), make_incident()]},
        ),
        "approvals": FakeOwnerApprovalReader({prop.id: [make_approval()]}),
        "expenses": FakeExpenseReader({prop.id: {"EUR": Decimal("75.00")}}),
        "timeline": FakeTimelineReader({prop.id: make_event(TENANT, prop.id)}),
    }


def _cards_use_case(world) -> GetDashboardCardsUseCase:
    return GetDashboardCardsUseCase(
        properties=world["properties"],
        reservations=world["reservations"],
        guests=world["guests"],
        cleaning=world["cleaning"],
        incidents=world["incidents"],
        timeline=world["timeline"],
    )


def _detail_use_case(world) -> GetPropertyDashboardUseCase:
    return GetPropertyDashboardUseCase(
        properties=world["properties"],
        reservations=world["reservations"],
        guests=world["guests"],
        cleaning=world["cleaning"],
        incidents=world["incidents"],
        approvals=world["approvals"],
        expenses=world["expenses"],
    )


async def _cards(world, role=UserRole.TENANT_OWNER, locale=Locale.ES):
    return await _cards_use_case(world).execute(
        tenant_id=TENANT, role=role, locale=locale, page=1, per_page=20, today=TODAY
    )


async def _detail(world, role=UserRole.TENANT_OWNER, locale=Locale.ES):
    return await _detail_use_case(world).execute(
        tenant_id=TENANT,
        property_id=world["property"].id,
        role=role,
        locale=locale,
        today=TODAY,
    )


# --- the card (R1.2, R1.3, R1.4) --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_card_carries_every_block_for_a_role_that_may_read_them_all(world) -> None:
    page = await _cards(world)

    assert page.total == 1
    card = page.items[0]
    assert card.property_id == world["property"].id
    assert card.property_code == "REDES11"
    assert card.operational_state is PropertyOperationalState.AWAITING_CLEANING
    assert card.current_or_next_reservation is not None
    assert card.current_or_next_reservation.guest_name == "Marta García"
    assert card.current_or_next_reservation.reference == "BOOKING #BK-1"
    assert card.cleaning_status == "Limpieza en curso"
    assert card.open_incidents_count == 2
    assert card.next_action is not None
    assert card.next_action.label == "Asignar limpiadora"
    assert card.next_action.responsible == "Gestor"
    assert card.last_event_label == "Limpieza completada"
    assert card.last_event_at is not None


@pytest.mark.asyncio
async def test_the_state_literal_is_not_translated(world) -> None:
    """R1.3 — the canonical value, whatever the reader's language."""
    page = await _cards(world, locale=Locale.EN)

    assert page.items[0].operational_state is PropertyOperationalState.AWAITING_CLEANING


@pytest.mark.asyncio
async def test_the_labels_follow_the_readers_language(world) -> None:
    page = await _cards(world, locale=Locale.EN)

    card = page.items[0]
    assert card.cleaning_status == "Cleaning in progress"
    assert card.next_action.label == "Assign a cleaner"
    assert card.next_action.responsible == "Manager"
    assert card.last_event_label == "Cleaning completed"


@pytest.mark.asyncio
async def test_a_property_with_no_reservation_gets_null_and_not_an_omission(world) -> None:
    """R1.4: "SHALL devolver `currentOrNextReservation: null` en vez de omitir la clave"."""
    world["reservations"] = FakeReservationRepository({TENANT: []})

    page = await _cards(world)

    card = page.items[0]
    assert card.current_or_next_reservation is None
    assert "current_or_next_reservation" in {f for f in card.__dataclass_fields__}


@pytest.mark.asyncio
async def test_a_property_with_no_incidents_counts_zero_not_none(world) -> None:
    world["incidents"] = FakeIncidentReader(counts={TENANT: {}})

    page = await _cards(world)

    assert page.items[0].open_incidents_count == 0


@pytest.mark.asyncio
async def test_a_resting_state_has_no_next_action(world) -> None:
    world["property"] = make_property(
        TENANT,
        state=PropertyOperationalState.VACANT_READY,
        property_id=world["property"].id,
    )
    world["properties"] = FakePropertyRepository({TENANT: [world["property"]]})

    page = await _cards(world)

    assert page.items[0].next_action is None


@pytest.mark.asyncio
async def test_an_empty_portfolio_reads_no_other_domain(world) -> None:
    """No properties means no ids to batch on — querying anyway would be five wasted round
    trips on the most common cold-start response."""
    world["properties"] = FakePropertyRepository({TENANT: []})

    page = await _cards(world)

    assert page.items == ()
    assert page.total == 0
    assert world["reservations"].calls == []
    assert world["cleaning"].calls == []


# --- omission by permission (R1.7, D10) --------------------------------------------------


@pytest.mark.asyncio
async def test_a_role_without_read_reservations_gets_no_reservation_block(world) -> None:
    """D10: "agregar no puede conceder". `CLEANER` is the role that actually lacks it —
    it never reaches the route today, which is exactly why the use case must not rely on
    the door for this."""
    page = await _cards(world, role=UserRole.CLEANER)

    assert page.items[0].current_or_next_reservation is None
    assert world["reservations"].calls == [], "it must not even ask"
    assert world["guests"].calls == [], "the guest rides with the reservation"


@pytest.mark.asyncio
async def test_a_role_without_read_cleaning_gets_no_cleaning_status(world) -> None:
    page = await _cards(world, role=UserRole.SUPER_ADMIN)

    assert page.items[0].cleaning_status is None
    assert world["cleaning"].calls == []


@pytest.mark.asyncio
async def test_the_incident_count_is_not_gated(world) -> None:
    """No permission guards `incidents` today — `maintenance` has none — so the count is
    not omitted. If that changes, this test is where the decision gets revisited."""
    page = await _cards(world, role=UserRole.SUPER_ADMIN)

    assert page.items[0].open_incidents_count == 2


# --- the detail (R2.1, R2.3, R2.4, R2.5) -------------------------------------------------


@pytest.mark.asyncio
async def test_the_detail_composes_every_section_of_prd_9_2(world) -> None:
    detail = await _detail(world)

    assert detail.property_code == "REDES11"
    assert detail.current_or_next_reservation is not None
    assert detail.guest is not None and detail.guest.name == "Marta García"
    assert detail.access is not None and detail.access.label == "Acceso entregado"
    assert detail.cleaning_status == "Limpieza en curso"
    assert len(detail.open_incidents) == 2
    assert detail.open_incidents[0].title == "Electrodoméstico averiado"
    assert detail.financial is not None
    assert detail.financial.pending_expenses == Decimal("75.00")
    assert detail.financial.reservation_total == Decimal("450.00")
    assert len(detail.pending_approvals) == 1
    assert detail.pending_approvals[0].label == "Aprobación de incidencia"


@pytest.mark.asyncio
async def test_the_blocks_without_a_writer_come_back_empty_not_absent(world) -> None:
    """R2.3: the tables are real and empty today, and the contract does not change when
    `maintenance` and `revenue` land."""
    world["incidents"] = FakeIncidentReader(counts={TENANT: {}}, open_by_property={})
    world["approvals"] = FakeOwnerApprovalReader({})
    world["expenses"] = FakeExpenseReader({})

    detail = await _detail(world)

    assert detail.open_incidents == ()
    assert detail.pending_approvals == ()
    assert detail.financial is not None
    assert detail.financial.pending_expenses is None


@pytest.mark.asyncio
async def test_the_cleaning_photos_are_always_empty(world) -> None:
    """R2.4, `EXTERNAL_DEPENDENCY`: a signed URL needs `StorageAdapter.get_signed_url`,
    which `cleaning-photos-storage` delivers. No storage key is ever exposed."""
    detail = await _detail(world)

    assert detail.last_cleaning_photos == ()


@pytest.mark.asyncio
async def test_the_notes_block_is_always_null(world) -> None:
    """Design D12: no column owns it, and the candidates are rule-11 plaintext sinks."""
    detail = await _detail(world)

    assert detail.notes is None


@pytest.mark.asyncio
async def test_the_detail_never_carries_a_document_or_a_code(world) -> None:
    """R2.5 — asserted over the rendered object, not only over the type."""
    detail = await _detail(world)

    rendered = repr(detail)
    for forbidden in ("document", "passport", "DNI", "code_masked"):
        assert forbidden not in rendered


@pytest.mark.asyncio
async def test_a_role_without_read_access_records_gets_no_access_block(world) -> None:
    detail = await _detail(world, role=UserRole.SUPER_ADMIN)

    assert detail.access is None


@pytest.mark.asyncio
async def test_a_role_without_read_reservations_gets_neither_reservation_nor_guest(
    world,
) -> None:
    """D10 pairs them: "`READ_RESERVATIONS` → reserva y huésped"."""
    detail = await _detail(world, role=UserRole.CLEANER)

    assert detail.current_or_next_reservation is None
    assert detail.guest is None


@pytest.mark.asyncio
async def test_the_access_block_is_gated_by_its_own_permission_not_the_reservations_one(
    world, monkeypatch
) -> None:
    """R2.7 lists the three permissions as independent gates.

    `access_status` is a column of `reservations`, so building the access block needs the
    stay — and the first version of this use case therefore gated it on `READ_RESERVATIONS`
    too, making `READ_ACCESS_RECORDS` useless without it. The QA panel of sections 6-7 found
    it by inventing exactly the role below. None exists today; the point is that none has to.
    """
    from app.auth.domain import policy
    from app.dashboard.application import use_cases as module

    allowed = {Permission.READ_PROPERTIES, Permission.READ_ACCESS_RECORDS}
    monkeypatch.setattr(module, "is_allowed", lambda role, permission: permission in allowed)

    detail = await _detail(world)

    assert detail.access is not None, "READ_ACCESS_RECORDS alone must yield the access block"
    assert detail.access.label == "Acceso entregado"
    # ...and it grants nothing else.
    assert detail.current_or_next_reservation is None
    assert detail.guest is None
    assert detail.cleaning_status is None
    assert world["guests"].calls == [], "the guest is not needed to report an access status"
    assert policy.is_allowed is not None  # the real policy is untouched by the patch


@pytest.mark.asyncio
async def test_the_financial_block_does_not_leak_the_stays_total_to_an_access_only_role(
    world, monkeypatch
) -> None:
    """The other half of the same rule, and the one the feature panel found.

    The access block needs the stay, so `READ_ACCESS_RECORDS` alone makes the use case read
    the reservation row (`use_cases.py:273`). The money block is built from that same row,
    and handing it over unconditionally published `reservation_total` — the stay's gross
    amount — to a role that `current_or_next_reservation` deliberately answers `null` for.
    D10: aggregating must not grant. The pending expenses are `statements`' own and stay.
    """
    from app.dashboard.application import use_cases as module

    allowed = {Permission.READ_PROPERTIES, Permission.READ_ACCESS_RECORDS}
    monkeypatch.setattr(module, "is_allowed", lambda role, permission: permission in allowed)

    detail = await _detail(world)

    assert detail.current_or_next_reservation is None
    assert detail.financial is not None
    assert detail.financial.reservation_total is None, (
        "the stay's total is the stay's: READ_ACCESS_RECORDS must not carry it"
    )
    # ...and withholding it does not blank the block the caller *is* entitled to.
    assert detail.financial.pending_expenses == Decimal("75.00")


@pytest.mark.asyncio
async def test_the_stays_currency_is_withheld_too_not_only_its_total(
    world, monkeypatch
) -> None:
    """The other half of the same leak, and the one the amount alone cannot pin.

    `financials.py:57` reads `reservation_currency` as well, so a regression that passed the
    stay back "just for the currency" would restore a leak the total-only assertion above
    would not see. It is observable only with **no** pending expenses: with one pending
    currency the block reports *that* one (`financials.py:59-65`) and the stay's is masked
    either way. So: no expenses, and a stay denominated in something other than the default.
    """
    from app.dashboard.application import use_cases as module

    allowed = {Permission.READ_PROPERTIES, Permission.READ_ACCESS_RECORDS}
    monkeypatch.setattr(module, "is_allowed", lambda role, permission: permission in allowed)
    world["reservations"] = FakeReservationRepository(
        {
            TENANT: [
                make_reservation(
                    TENANT, world["property"].id, guest_id=world["guest_id"], currency="GBP"
                )
            ]
        }
    )
    world["expenses"] = FakeExpenseReader({})

    detail = await _detail(world)

    assert detail.financial is not None
    assert detail.financial.currency == "EUR", (
        "the stay's currency is the stay's: without READ_RESERVATIONS the block falls back "
        "to the default, it does not borrow GBP from the row it was allowed to read"
    )
    assert detail.financial.reservation_total is None


@pytest.mark.asyncio
async def test_a_role_with_neither_permission_does_not_read_the_stay_at_all(
    world, monkeypatch
) -> None:
    """The other side of the same rule: reading the row is not the same as publishing it,
    but a role that needs neither block must not cause the query either."""
    from app.dashboard.application import use_cases as module

    allowed = {Permission.READ_PROPERTIES}
    monkeypatch.setattr(module, "is_allowed", lambda role, permission: permission in allowed)

    detail = await _detail(world)

    assert detail.access is None
    assert detail.current_or_next_reservation is None
    assert world["reservations"].calls == []


@pytest.mark.asyncio
async def test_a_stay_beyond_the_lookahead_horizon_is_not_shown(world) -> None:
    """`RESERVATION_LOOKAHEAD_DAYS` is an `ASSUMPTION`, so the boundary is pinned: a change
    to the constant or to the query window has to move this test deliberately."""
    from datetime import timedelta

    from app.dashboard.application.use_cases import RESERVATION_LOOKAHEAD_DAYS

    beyond = TODAY + timedelta(days=RESERVATION_LOOKAHEAD_DAYS + 5)
    world["reservations"] = FakeReservationRepository(
        {
            TENANT: [
                make_reservation(
                    TENANT,
                    world["property"].id,
                    check_in=beyond,
                    check_out=beyond + timedelta(days=2),
                )
            ]
        }
    )

    page = await _cards(world)

    assert page.items[0].current_or_next_reservation is None


@pytest.mark.asyncio
async def test_a_stay_inside_the_lookahead_horizon_is_shown(world) -> None:
    """The other half, so the test above cannot pass because the window is broken entirely."""
    from datetime import timedelta

    from app.dashboard.application.use_cases import RESERVATION_LOOKAHEAD_DAYS

    inside = TODAY + timedelta(days=RESERVATION_LOOKAHEAD_DAYS - 5)
    world["reservations"] = FakeReservationRepository(
        {
            TENANT: [
                make_reservation(
                    TENANT,
                    world["property"].id,
                    check_in=inside,
                    check_out=inside + timedelta(days=2),
                    external_pms_id="FUTURE",
                )
            ]
        }
    )

    page = await _cards(world)

    assert page.items[0].current_or_next_reservation is not None
    assert page.items[0].current_or_next_reservation.reference == "BOOKING #FUTURE"


@pytest.mark.asyncio
async def test_an_unknown_property_raises_the_not_found_the_route_maps_to_404(world) -> None:
    with pytest.raises(PropertyNotFoundError):
        await _detail_use_case(world).execute(
            tenant_id=TENANT,
            property_id=uuid.uuid4(),
            role=UserRole.TENANT_OWNER,
            locale=Locale.ES,
            today=TODAY,
        )


@pytest.mark.asyncio
async def test_a_property_of_another_tenant_raises_the_very_same_error(world) -> None:
    """R2.2, design D11 — the use case cannot tell the two apart, which is the point."""
    with pytest.raises(PropertyNotFoundError):
        await _detail_use_case(world).execute(
            tenant_id=OTHER_TENANT,
            property_id=world["property"].id,
            role=UserRole.TENANT_OWNER,
            locale=Locale.ES,
            today=TODAY,
        )


# --- the reservation chosen (R1.2) -------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stay_in_progress_beats_a_later_one(world) -> None:
    from datetime import date as _date

    later = make_reservation(
        TENANT,
        world["property"].id,
        check_in=_date(2026, 8, 20),
        check_out=_date(2026, 8, 25),
        external_pms_id="BK-2",
    )
    world["reservations"] = FakeReservationRepository(
        {TENANT: [later, world["reservation"]]}
    )

    page = await _cards(world)

    assert page.items[0].current_or_next_reservation.reference == "BOOKING #BK-1"


@pytest.mark.asyncio
async def test_a_stay_that_already_ended_is_not_the_current_one(world) -> None:
    from datetime import date as _date

    past = make_reservation(
        TENANT,
        world["property"].id,
        check_in=_date(2026, 7, 1),
        check_out=_date(2026, 7, 5),
        external_pms_id="OLD",
    )
    world["reservations"] = FakeReservationRepository({TENANT: [past]})

    page = await _cards(world)

    assert page.items[0].current_or_next_reservation is None


@pytest.mark.asyncio
async def test_a_reservation_without_a_guest_still_produces_a_block(world) -> None:
    world["reservations"] = FakeReservationRepository(
        {TENANT: [make_reservation(TENANT, world["property"].id, guest_id=None)]}
    )

    page = await _cards(world)

    block = page.items[0].current_or_next_reservation
    assert block is not None
    assert block.guest_name is None


@pytest.mark.asyncio
async def test_a_reservation_without_an_external_id_reports_just_the_channel(world) -> None:
    world["reservations"] = FakeReservationRepository(
        {
            TENANT: [
                make_reservation(TENANT, world["property"].id, external_pms_id=None)
            ]
        }
    )

    page = await _cards(world)

    assert page.items[0].current_or_next_reservation.reference == "BOOKING"


# --- money -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_currencies_report_no_total_rather_than_a_meaningless_sum(world) -> None:
    """`ExpenseReader` refuses to choose; this is where the choice is made, and it is to
    say nothing rather than add up amounts that are not comparable."""
    world["expenses"] = FakeExpenseReader(
        {world["property"].id: {"EUR": Decimal("10.00"), "GBP": Decimal("20.00")}}
    )

    detail = await _detail(world)

    assert detail.financial is not None
    assert detail.financial.pending_expenses is None


# --- the occupancy series (`dashboard-occupancy-series` R1, R4.1, R4.3, D5) --------------


def _occupancy_use_case(*, properties, reservations, transitions) -> GetOccupancySeriesUseCase:
    return GetOccupancySeriesUseCase(
        properties=properties, reservations=reservations, transitions=transitions
    )


@pytest.mark.asyncio
async def test_a_role_without_read_reservations_gets_a_null_series_and_costs_zero_queries() -> (
    None
):
    """D5: the whole series is redacted as one boundary check, not built from
    blocks/out-of-service days alone (R4.3) — and the check happens before any port is
    touched, unlike `PropertyDashboardCard`'s per-block gating above."""
    prop = make_property(TENANT)
    properties = FakePropertyRepository({TENANT: [prop]})
    reservations = FakeReservationRepository({TENANT: [make_reservation(TENANT, prop.id)]})
    transitions = FakePropertyStateTransitionRepository()
    use_case = _occupancy_use_case(
        properties=properties, reservations=reservations, transitions=transitions
    )

    series = await use_case.execute(tenant_id=TENANT, role=UserRole.CLEANER, today=TODAY)

    assert series is None
    assert properties.calls == []
    assert reservations.calls == []
    assert transitions.calls == []


@pytest.mark.asyncio
async def test_an_empty_portfolio_gets_seven_points_of_zero_total() -> None:
    """R1: still seven points, ordered Monday to Sunday, `total_properties == 0` on all —
    never an empty tuple, never a division by zero (R1.3, delegated to `occupancy_series`)."""
    properties = FakePropertyRepository({TENANT: []})
    reservations = FakeReservationRepository({TENANT: []})
    transitions = FakePropertyStateTransitionRepository()
    use_case = _occupancy_use_case(
        properties=properties, reservations=reservations, transitions=transitions
    )

    series = await use_case.execute(tenant_id=TENANT, role=UserRole.TENANT_OWNER, today=TODAY)

    assert series is not None
    assert len(series) == 7
    assert all(point.total_properties == 0 for point in series)
    assert all(point.occupied_properties == 0 for point in series)
    assert all(point.occupancy_pct is None for point in series)
    week_start, _ = week_bounds(TODAY)
    assert [point.date for point in series] == [
        week_start + timedelta(days=offset) for offset in range(7)
    ]


@pytest.mark.asyncio
async def test_tenant_id_is_sourced_from_the_caller_and_passed_to_every_port_call() -> None:
    """R4.1: never a request parameter. Proven by recording what each fake actually
    received, not merely what the use case's own signature accepts."""
    prop = make_property(TENANT)
    properties = FakePropertyRepository({TENANT: [prop]})
    reservations = FakeReservationRepository({TENANT: [make_reservation(TENANT, prop.id)]})
    transitions = FakePropertyStateTransitionRepository()
    use_case = _occupancy_use_case(
        properties=properties, reservations=reservations, transitions=transitions
    )
    week_start, week_end = week_bounds(TODAY)

    await use_case.execute(tenant_id=TENANT, role=UserRole.TENANT_OWNER, today=TODAY)

    assert properties.calls == [("list_by_status", TENANT, PropertyStatus.ACTIVE)]
    assert reservations.calls == [(TENANT, (prop.id,), week_start, week_end)]
    assert transitions.calls == [
        ("history_for_properties", TENANT, (prop.id,), week_start, week_end)
    ]


@pytest.mark.asyncio
async def test_a_reservation_produces_an_occupied_night_in_the_series() -> None:
    """Composition, end to end over the fakes: a stay covering the week's Monday shows up
    as one occupied property on that day and nowhere else, with the right denominator."""
    week_start, _ = week_bounds(TODAY)
    prop = make_property(TENANT)
    stay = make_reservation(
        TENANT, prop.id, check_in=week_start, check_out=week_start + timedelta(days=1)
    )
    properties = FakePropertyRepository({TENANT: [prop]})
    reservations = FakeReservationRepository({TENANT: [stay]})
    transitions = FakePropertyStateTransitionRepository()
    use_case = _occupancy_use_case(
        properties=properties, reservations=reservations, transitions=transitions
    )

    series = await use_case.execute(tenant_id=TENANT, role=UserRole.TENANT_OWNER, today=TODAY)

    assert series is not None
    assert len(series) == 7
    assert series[0].date == week_start
    assert series[0].occupied_properties == 1
    assert series[0].total_properties == 1
    assert series[1].occupied_properties == 0
