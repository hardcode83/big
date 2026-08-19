"""`GetCleaningTaskContextUseCase` against fakes of its three ports (R2, R3, design D2).

No database. What only this level can pin is **which tenant id each repository was asked for**:
D2's whole claim is that composing three tenant-scoped `get`s is stricter than a `JOIN`, because
"cada `get` lleva su `tenant_id` explícito, así que una tarea que apunte a la propiedad de otro
tenant devuelve `None` → 404". A fake that records its arguments is what turns that from an
assertion into a demonstration — the design says so itself: "Aquí D2 lo cierra por composición,
pero eso hay que demostrarlo, no afirmarlo."

The serialised-body half of R1.4/R2.5 is not here and cannot be: a fake returns objects. That the
forbidden keys never reach the wire is `test_task_context_api.py`'s assertion, against the real
body; the field set itself is pinned in `test_task_context_read_model.py`.
"""

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.auth.domain.enums import UserRole
from app.cleaning.application.use_cases import (
    CleaningActor,
    GetCleaningTaskContextUseCase,
)
from app.cleaning.domain.entities import CleaningTask
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import CleaningTaskNotFoundError
from app.properties.domain.entities import Property
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus

MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
CLEANER = uuid.uuid4()
OTHER_CLEANER = uuid.uuid4()
MANAGER = uuid.uuid4()
OWNER = uuid.uuid4()


def _property(tenant_id: uuid.UUID = TENANT) -> Property:
    return Property(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Redes 11",
        internal_code="REDES11",
        created_at=NOW,
        updated_at=NOW,
        address_line1="Calle de Redes 11",
        address_line2=None,
        city="Madrid",
        province="Madrid",
        postal_code="28029",
        country="ES",
        timezone="Europe/Madrid",
        default_check_out_time=time(11, 0),
        default_check_in_time=time(15, 0),
        access_notes="Llaves en el buzón",
        cleaning_notes="Aspirar el sofá",
        emergency_notes="Portero: 600000000",
    )


def _reservation(
    prop: Property,
    *,
    check_in: date,
    nights: int = 2,
    check_in_time: time | None = None,
    check_out_time: time | None = None,
    status: ReservationStatus = ReservationStatus.CONFIRMED,
) -> Reservation:
    return Reservation.create(
        id=uuid.uuid4(),
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        channel=ReservationChannel.AIRBNB,
        check_in_date=check_in,
        check_out_date=check_in + timedelta(days=nights),
        now=NOW,
        adults=2,
        check_in_time=check_in_time,
        check_out_time=check_out_time,
        status=status,
        gross_amount=None,
    )


def _task(
    prop: Property,
    *,
    reservation: Reservation | None = None,
    cleaner: uuid.UUID | None = CLEANER,
) -> CleaningTask:
    return CleaningTask(
        id=uuid.uuid4(),
        tenant_id=prop.tenant_id,
        property_id=prop.id,
        checklist_template_id=uuid.uuid4(),
        created_at=NOW,
        updated_at=NOW,
        reservation_id=reservation.id if reservation is not None else None,
        assigned_cleaner_id=cleaner,
        status=CleaningTaskStatus.CREATED,
    )


class FakeTaskRepository:
    def __init__(self, task: CleaningTask | None) -> None:
        self._task = task

    async def get(self, tenant_id, task_id):
        if self._task is None:
            return None
        if tenant_id != self._task.tenant_id or task_id != self._task.id:
            return None
        return self._task


class FakePropertyRepository:
    """Records every (tenant, property) it was asked about — D2's claim is about those ids."""

    def __init__(self, property: Property | None) -> None:
        self._property = property
        self.queried: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def get(self, tenant_id, property_id):
        self.queried.append((tenant_id, property_id))
        if self._property is None:
            return None
        if tenant_id != self._property.tenant_id or property_id != self._property.id:
            return None
        return self._property


class FakeReservationRepository:
    """Records both calls: the outgoing stay's `get` and the candidates' window."""

    def __init__(
        self,
        *,
        reservation: Reservation | None = None,
        candidates: list[Reservation] | None = None,
    ) -> None:
        self._reservation = reservation
        self._candidates = candidates or []
        self.got: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.listed: list[tuple[uuid.UUID, list[uuid.UUID], date, date]] = []

    async def get(self, tenant_id, reservation_id):
        self.got.append((tenant_id, reservation_id))
        if self._reservation is None:
            return None
        if tenant_id != self._reservation.tenant_id or reservation_id != self._reservation.id:
            return None
        return self._reservation

    async def list_for_properties(self, tenant_id, property_ids, date_from, date_to):
        self.listed.append((tenant_id, list(property_ids), date_from, date_to))
        return [
            candidate
            for candidate in self._candidates
            if candidate.tenant_id == tenant_id and candidate.property_id in set(property_ids)
        ]


def _use_case(
    task: CleaningTask | None,
    property: Property | None,
    *,
    reservation: Reservation | None = None,
    candidates: list[Reservation] | None = None,
) -> tuple[GetCleaningTaskContextUseCase, FakePropertyRepository, FakeReservationRepository]:
    properties = FakePropertyRepository(property)
    reservations = FakeReservationRepository(reservation=reservation, candidates=candidates)
    use_case = GetCleaningTaskContextUseCase(
        tasks=FakeTaskRepository(task), properties=properties, reservations=reservations
    )
    return use_case, properties, reservations


def _actor(user_id: uuid.UUID, role: UserRole) -> CleaningActor:
    return CleaningActor(user_id=user_id, role=role)


async def _execute(use_case, task, actor):
    return await use_case.execute(
        tenant_id=task.tenant_id, task_id=task.id, actor=actor, now=NOW
    )


class TestTheTwoInstants:
    @pytest.mark.asyncio
    async def test_a_task_with_an_outgoing_stay_reports_both(self) -> None:
        """R2.1, R2.2 — the checkout of the outgoing stay and the next arrival after it."""
        prop = _property()
        outgoing = _reservation(prop, check_in=date(2026, 8, 10), check_out_time=time(10, 30))
        arrival = _reservation(prop, check_in=date(2026, 8, 13), check_in_time=time(16, 0))
        task = _task(prop, reservation=outgoing)
        use_case, _, _ = _use_case(
            task, prop, reservation=outgoing, candidates=[outgoing, arrival]
        )

        context = await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert context.checkout_at == datetime(2026, 8, 12, 10, 30, tzinfo=MADRID)
        assert context.next_checkin_deadline == datetime(2026, 8, 13, 16, 0, tzinfo=MADRID)

    @pytest.mark.asyncio
    async def test_a_manual_task_without_a_reservation_has_no_checkout_and_anchors_on_now(
        self,
    ) -> None:
        """Design D6 — `POST /cleaning-tasks` with no stay is legitimate, so `null`, not an error.

        The deadline still resolves, measured from `now`: an arrival tomorrow is a deadline for a
        manual task exactly as it is for an automatic one.
        """
        prop = _property()
        arrival = _reservation(prop, check_in=date(2026, 8, 13), check_in_time=time(16, 0))
        task = _task(prop, reservation=None)
        use_case, _, reservations = _use_case(task, prop, candidates=[arrival])

        context = await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert context.checkout_at is None
        assert context.next_checkin_deadline == datetime(2026, 8, 13, 16, 0, tzinfo=MADRID)
        # No outgoing stay to fetch, so the reservation `get` is never made.
        assert reservations.got == []
        # …and the window anchors on `now` (D6), not on an absent checkout.
        assert reservations.listed[0][2] == NOW.date()

    @pytest.mark.asyncio
    async def test_no_later_arrival_leaves_the_deadline_null(self) -> None:
        """R2.3 — `null`, not an invented date and not an error."""
        prop = _property()
        outgoing = _reservation(prop, check_in=date(2026, 8, 10), check_out_time=time(10, 30))
        task = _task(prop, reservation=outgoing)
        use_case, _, _ = _use_case(task, prop, reservation=outgoing, candidates=[outgoing])

        context = await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert context.checkout_at == datetime(2026, 8, 12, 10, 30, tzinfo=MADRID)
        assert context.next_checkin_deadline is None

    @pytest.mark.asyncio
    async def test_an_arrival_beyond_the_horizon_is_not_a_deadline(self) -> None:
        """Design D10, pinned at the use case — **not** left to how the fetch window rounded.

        `list_for_properties` takes `date`s, so a fake that ignores the window (as a permissive
        repository would) still hands over an arrival past the horizon. The value has to be
        clamped for `null` to mean "no `CONFIRMED` arrival within 14 days of the anchor".
        """
        prop = _property()
        outgoing = _reservation(prop, check_in=date(2026, 8, 10), check_out_time=time(10, 30))
        # Checkout is 2026-08-12 10:30 Madrid, so the horizon ends 2026-08-26 10:30.
        far = _reservation(prop, check_in=date(2026, 9, 5), check_in_time=time(16, 0))
        task = _task(prop, reservation=outgoing)
        use_case, _, _ = _use_case(task, prop, reservation=outgoing, candidates=[outgoing, far])

        context = await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert context.next_checkin_deadline is None

    @pytest.mark.asyncio
    async def test_an_arrival_just_inside_the_horizon_is_a_deadline(self) -> None:
        """The other side of D10's boundary, so the clamp cannot pass by rejecting everything."""
        prop = _property()
        outgoing = _reservation(prop, check_in=date(2026, 8, 10), check_out_time=time(10, 30))
        near = _reservation(prop, check_in=date(2026, 8, 25), check_in_time=time(16, 0))
        task = _task(prop, reservation=outgoing)
        use_case, _, _ = _use_case(task, prop, reservation=outgoing, candidates=[outgoing, near])

        context = await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert context.next_checkin_deadline == datetime(2026, 8, 25, 16, 0, tzinfo=MADRID)

    @pytest.mark.asyncio
    async def test_the_tasks_own_stay_is_not_counted_as_an_arrival(self) -> None:
        """R2.2 — the outgoing stay overlaps the window and must not be its own deadline."""
        prop = _property()
        # Check-in is *after* the anchor, so without the exclusion it would win the `min`.
        outgoing = _reservation(prop, check_in=date(2026, 8, 13), check_out_time=time(10, 30))
        task = _task(prop, reservation=outgoing)
        use_case, _, _ = _use_case(task, prop, reservation=outgoing, candidates=[outgoing])

        context = await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert context.next_checkin_deadline is None

    @pytest.mark.asyncio
    async def test_the_address_survives_a_reservation_that_does_not_resolve(self, caplog) -> None:
        """A dangling `reservation_id` costs the checkout, not the whole context.

        The address is most of what PRD §11 asks this route for, so refusing everything over a
        pointer that does not resolve would deny the cleaner exactly what she came for.
        """
        prop = _property()
        outgoing = _reservation(prop, check_in=date(2026, 8, 10))
        task = _task(prop, reservation=outgoing)
        use_case, _, _ = _use_case(task, prop, reservation=None)

        with caplog.at_level(logging.WARNING, logger="app.cleaning.application.use_cases"):
            context = await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert context.checkout_at is None
        assert context.address_line1 == "Calle de Redes 11"
        # The degradation is deliberate (design D6 addendum) but it is an anomaly, so it must not
        # pass silently — asserting the record is what keeps "and it is logged" from being a claim.
        assert [record.message for record in caplog.records] == [
            "cleaning.task_context_reservation_missing"
        ]

    @pytest.mark.asyncio
    async def test_a_reservation_that_resolves_in_another_tenant_degrades_the_same_way(
        self, caplog
    ) -> None:
        """The other half of the D6 addendum: a *crossed* pointer, not just a missing one.

        The addendum's security argument is that "una reserva de otro tenant y una inexistente
        producen el mismo `None`, así que la rama no es un oráculo de existencia". That only holds
        if the tenant-scoped `get` is what produces the `None`, so it is asserted here rather than
        inferred from the missing-id case above: the repository is asked with the *caller's*
        tenant, the foreign row does not come back, and the outcome is byte-identical to a
        reservation that never existed.
        """
        prop = _property()
        foreign = _reservation(_property(OTHER_TENANT), check_in=date(2026, 8, 10))
        task = _task(prop, reservation=foreign)
        use_case, _, reservations = _use_case(task, prop, reservation=foreign)

        with caplog.at_level(logging.WARNING, logger="app.cleaning.application.use_cases"):
            context = await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        # The caller's tenant is what went to the repository — never the row's own.
        assert reservations.got == [(TENANT, foreign.id)]
        assert context.checkout_at is None
        assert context.address_line1 == "Calle de Redes 11"
        assert [record.message for record in caplog.records] == [
            "cleaning.task_context_reservation_missing"
        ]


class TestTheProjectedFields:
    @pytest.mark.asyncio
    async def test_it_reports_the_properties_identity_address_and_zone(self) -> None:
        """R1.1, R1.2 — and none of R1.4's forbidden fields has anywhere to land (D3)."""
        prop = _property()
        task = _task(prop, reservation=None)
        use_case, _, _ = _use_case(task, prop)

        context = await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert context.property_name == "Redes 11"
        assert context.property_internal_code == "REDES11"
        assert context.city == "Madrid"
        assert context.province == "Madrid"
        assert context.postal_code == "28029"
        assert context.country == "ES"
        assert context.timezone == "Europe/Madrid"

    @pytest.mark.asyncio
    async def test_a_null_address_field_stays_null(self) -> None:
        """R1.3's domain half — the `None` is carried, not substituted with an empty string."""
        prop = _property()
        task = _task(prop, reservation=None)
        use_case, _, _ = _use_case(task, prop)

        context = await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert context.address_line2 is None


class TestTheRowLevelRule:
    @pytest.mark.asyncio
    async def test_a_cleaner_cannot_reach_another_cleaners_task(self) -> None:
        """R3.2 — `CleaningTaskNotFoundError`, the same error an unknown id raises."""
        prop = _property()
        task = _task(prop, cleaner=OTHER_CLEANER)
        use_case, properties, _ = _use_case(task, prop)

        with pytest.raises(CleaningTaskNotFoundError):
            await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        # And it refused *before* reading the property: nothing about it was even fetched.
        assert properties.queried == []

    @pytest.mark.asyncio
    async def test_an_unknown_task_raises_the_same_error(self) -> None:
        """R3.2's other half — the two outcomes must be indistinguishable."""
        prop = _property()
        use_case, _, _ = _use_case(None, prop)

        with pytest.raises(CleaningTaskNotFoundError):
            await use_case.execute(
                tenant_id=TENANT, task_id=uuid.uuid4(), actor=_actor(CLEANER, UserRole.CLEANER), now=NOW
            )

    @pytest.mark.asyncio
    async def test_another_tenants_task_is_not_found(self) -> None:
        """R3.3, and rule 1 of `steering/security.md` — the mandatory isolation case."""
        prop = _property(tenant_id=OTHER_TENANT)
        task = _task(prop)
        use_case, _, _ = _use_case(task, prop)

        with pytest.raises(CleaningTaskNotFoundError):
            await use_case.execute(
                tenant_id=TENANT, task_id=task.id, actor=_actor(CLEANER, UserRole.CLEANER), now=NOW
            )

    @pytest.mark.asyncio
    async def test_a_task_pointing_at_another_tenants_property_is_not_found(self) -> None:
        """The row D2 claims composition closes, demonstrated rather than asserted.

        The task is in this tenant; its `property_id` names a property that is not. Each `get`
        carries its own `tenant_id`, so the property resolves to `None` — the case
        `guest-portal-api`'s security panel had to close by hand with a second `WHERE` inside a
        join. The fake asserts the tenant it was asked for, so this cannot pass by accident.
        """
        prop = _property()
        foreign = _property(tenant_id=OTHER_TENANT)
        task = _task(prop)
        task.property_id = foreign.id
        use_case, properties, _ = _use_case(task, foreign)

        with pytest.raises(CleaningTaskNotFoundError):
            await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert properties.queried == [(TENANT, foreign.id)]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("user_id", "role"),
        [(MANAGER, UserRole.PROPERTY_MANAGER), (OWNER, UserRole.TENANT_OWNER)],
        ids=["property_manager", "tenant_owner"],
    )
    async def test_a_manager_or_owner_reaches_a_task_that_is_not_theirs(
        self, user_id: uuid.UUID, role: UserRole
    ) -> None:
        """R3.5 — `restrict_to_cleaner_id` is `None` for both, so the row rule does not apply."""
        prop = _property()
        task = _task(prop, cleaner=OTHER_CLEANER)
        use_case, _, _ = _use_case(task, prop)

        context = await _execute(use_case, task, _actor(user_id, role))

        assert context.property_internal_code == "REDES11"


class TestTheQueriesItMakes:
    @pytest.mark.asyncio
    async def test_every_read_carries_the_callers_tenant_and_the_window_is_the_horizon(
        self,
    ) -> None:
        """D2 — "cada `get` lleva su `tenant_id` explícito" — and D10's window, both checked.

        Without this, "no `SELECT` nuevo, ningún adaptador de proyección" would be a claim about
        code shape rather than about the ids the reads actually used.
        """
        prop = _property()
        outgoing = _reservation(prop, check_in=date(2026, 8, 10), check_out_time=time(10, 30))
        task = _task(prop, reservation=outgoing)
        use_case, properties, reservations = _use_case(
            task, prop, reservation=outgoing, candidates=[outgoing]
        )

        await _execute(use_case, task, _actor(CLEANER, UserRole.CLEANER))

        assert properties.queried == [(TENANT, prop.id)]
        assert reservations.got == [(TENANT, outgoing.id)]
        tenant_id, property_ids, date_from, date_to = reservations.listed[0]
        assert tenant_id == TENANT
        assert property_ids == [prop.id]
        # Anchored on the checkout (2026-08-12 10:30 Madrid) and 14 days wide (D10).
        assert date_from == date(2026, 8, 12)
        assert date_to == date(2026, 8, 26)
