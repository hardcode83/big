"""Composing the dashboard (`dashboard-api` R1, R2, design D1/D2/D9/D10).

The `application/` layer of a module with **no `infrastructure/` of its own** (D1): every
port it holds belongs to another domain, and this file is where their answers are joined.
There is no SQL here and there must never be — D2 rejected a dashboard-owned adapter
because it "sería el segundo sitio donde se escribe el scope de tenant".

**The rule that shapes the whole file: a fixed number of queries.** R1.7 forbids one query
per property, and the design says why an assertion rather than a metric — "un `for` en el
caso de uso que llame a un `get` por propiedad es sintácticamente idéntico al código
correcto". So the collection reads each domain **once, in a batch**, and groups in memory.
`tests/dashboard/test_no_n_plus_one.py` counts statements and would fail on a loop.

**And the rule that shapes what comes back: aggregating cannot grant** (D10). `require()`
takes one permission, so a route gated on `READ_PROPERTIES` alone would hand a caller, in
one response, what four permissions protect separately. Each block is therefore omitted
when the calling role lacks the permission that guards its *source*. `is_allowed` is a pure
function of `app/auth/domain/policy.py`, so this costs no infrastructure.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.auth.domain.enums import UserRole
from app.auth.domain.policy import Permission, is_allowed
from app.cleaning.domain.repositories import CleaningTaskRepository
from app.cleaning.domain.value_objects import CleaningTaskSummary
from app.core.i18n import Locale
from app.dashboard.domain.financials import DEFAULT_CURRENCY, financial_block
from app.dashboard.domain.labels import (
    ACCESS_STATUS_LABELS,
    APPROVAL_LABELS,
    CLEANING_STATUS_LABELS,
    INCIDENT_TITLE_LABELS,
    NEXT_ACTION_LABELS,
    RESPONSIBLE_LABELS,
)
from app.dashboard.domain.next_action import next_action_for
from app.dashboard.domain.read_models import (
    AccessBlock,
    ApprovalBlock,
    CleaningPhotoBlock,
    FinancialBlock,
    GuestBlock,
    IncidentBlock,
    NextActionBlock,
    OpenIncidentCountsBlock,
    OperationalKpis,
    PropertyDashboardCard,
    PropertyDetail,
    ReservationBlock,
)
from app.guests.domain.repositories import GuestRepository
from app.maintenance.domain.repositories import IncidentReader, OwnerApprovalReader
from app.maintenance.domain.value_objects import OpenIncidentCounts
from app.properties.domain.entities import Property
from app.properties.domain.exceptions import PropertyNotFoundError
from app.properties.domain.repositories import PropertyFilters, PropertyRepository
from app.reservations.domain.entities import Reservation
from app.reservations.domain.repositories import ReservationRepository
from app.statements.domain.repositories import ExpenseReader
from app.timeline.domain.rendering import render
from app.timeline.domain.repositories import TimelineEventReader

# ASSUMPTION (R1.2): "current or next reservation" needs a horizon, and neither PRD §9.1 nor
# the frontend contract gives one. Ninety days is chosen to be longer than any booking
# window an operator watches on a dashboard and short enough to keep the batch query cheap.
# A property whose next stay is further out shows `null`, which is the honest answer for a
# screen that asks "what is happening now".
RESERVATION_LOOKAHEAD_DAYS = 90

# ASSUMPTION (R2): the check-in window `GetOperationalKpisUseCase` counts is not in the PRD
# nor the mockup — decided with Jose while writing the proposal. Its own constant, distinct
# from `RESERVATION_LOOKAHEAD_DAYS` above (design D6): that one bounds "the one stay to show
# on a card", this one is the literal count window R2.1 asks for, and conflating them would
# make a future change to either silently change the other.
UPCOMING_CHECKIN_WINDOW_DAYS = 7

# EXTERNAL_DEPENDENCY (R2.4): `cleaning_photos` stores a `storage_key`, and turning one into
# a URL is `StorageAdapter.get_signed_url`, which `cleaning-photos-storage` delivers. Rule 5
# of `steering/security.md` forbids exposing the internal path, so the only correct value
# until that adapter exists is none at all. The field is declared so the contract does not
# change when it does (design D9).
_NO_CLEANING_PHOTOS: tuple[CleaningPhotoBlock, ...] = ()


@dataclass(frozen=True)
class CardsPage:
    items: tuple[PropertyDashboardCard, ...]
    total: int


class GetDashboardCardsUseCase:
    """`GET /api/v1/dashboard/properties` (R1).

    Five batch reads and a grouping pass, whatever the page size.
    """

    def __init__(
        self,
        *,
        properties: PropertyRepository,
        reservations: ReservationRepository,
        guests: GuestRepository,
        cleaning: CleaningTaskRepository,
        incidents: IncidentReader,
        timeline: TimelineEventReader,
    ) -> None:
        self._properties = properties
        self._reservations = reservations
        self._guests = guests
        self._cleaning = cleaning
        self._incidents = incidents
        self._timeline = timeline

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        role: UserRole,
        locale: Locale,
        page: int,
        per_page: int,
        today: date,
    ) -> CardsPage:
        found = await self._properties.list(
            tenant_id, filters=PropertyFilters(), page=page, per_page=per_page
        )
        property_ids = [item.id for item in found.items]
        if not property_ids:
            return CardsPage(items=(), total=found.total)

        may_read_reservations = is_allowed(role, Permission.READ_RESERVATIONS)
        may_read_cleaning = is_allowed(role, Permission.READ_CLEANING_TASKS)

        reservations_by_property: dict[uuid.UUID, Reservation] = {}
        guests_by_id = {}
        if may_read_reservations:
            reservations = await self._reservations.list_for_properties(
                tenant_id,
                property_ids,
                today,
                today + timedelta(days=RESERVATION_LOOKAHEAD_DAYS),
            )
            reservations_by_property = _current_or_next_per_property(reservations, today)
            guest_ids = [
                reservation.guest_id
                for reservation in reservations_by_property.values()
                if reservation.guest_id is not None
            ]
            guests_by_id = {
                guest.id: guest
                for guest in await self._guests.list_for_ids(tenant_id, guest_ids)
            }

        cleaning_by_property: dict[uuid.UUID, CleaningTaskSummary] = {}
        if may_read_cleaning:
            cleaning_by_property = _one_live_task_per_property(
                await self._cleaning.list_live_for_properties(tenant_id, property_ids)
            )

        open_counts = await self._incidents.count_open_for_properties(tenant_id, property_ids)
        last_events = await self._timeline.last_for_properties(tenant_id, property_ids)

        cards = tuple(
            self._card(
                property=item,
                locale=locale,
                reservation=reservations_by_property.get(item.id),
                guests_by_id=guests_by_id,
                cleaning=cleaning_by_property.get(item.id),
                open_incidents=open_counts.get(item.id, 0),
                last_event=last_events.get(item.id),
                may_read_reservations=may_read_reservations,
                may_read_cleaning=may_read_cleaning,
            )
            for item in found.items
        )
        return CardsPage(items=cards, total=found.total)

    def _card(
        self,
        *,
        property: Property,
        locale: Locale,
        reservation: Reservation | None,
        guests_by_id: Mapping[uuid.UUID, object],
        cleaning: CleaningTaskSummary | None,
        open_incidents: int,
        last_event,
        may_read_reservations: bool,
        may_read_cleaning: bool,
    ) -> PropertyDashboardCard:
        rendered_event = render(last_event, locale) if last_event is not None else None
        return PropertyDashboardCard(
            property_id=property.id,
            property_code=property.internal_code,
            operational_state=property.current_operational_state,
            # `None` both when the role may not see reservations and when there is none —
            # D10's omission is deliberately indistinguishable from absence, because telling
            # them apart would itself disclose what the role may not see.
            current_or_next_reservation=(
                _reservation_block(reservation, guests_by_id)
                if may_read_reservations and reservation is not None
                else None
            ),
            cleaning_status=(
                CLEANING_STATUS_LABELS.render(cleaning.status.value, locale)
                if may_read_cleaning and cleaning is not None
                else None
            ),
            open_incidents_count=open_incidents,
            next_action=_next_action_block(property.current_operational_state, locale),
            # The rendered title, never the stored English one — and never the raw event,
            # whose `metadata` R4.3 keeps out of the read contract (security panel, §4).
            last_event_label=rendered_event.title if rendered_event is not None else None,
            last_event_at=rendered_event.occurred_at if rendered_event is not None else None,
        )


class GetPropertyDashboardUseCase:
    """`GET /api/v1/properties/{id}/dashboard` — the aggregate of PRD §9.2 (R2).

    One property, so the batch discipline of the collection does not apply; what applies is
    D9: **the blocks whose writer does not exist yet still query their real table** and come
    back empty, so the contract does not change when `maintenance` and `revenue` land.
    """

    def __init__(
        self,
        *,
        properties: PropertyRepository,
        reservations: ReservationRepository,
        guests: GuestRepository,
        cleaning: CleaningTaskRepository,
        incidents: IncidentReader,
        approvals: OwnerApprovalReader,
        expenses: ExpenseReader,
    ) -> None:
        self._properties = properties
        self._reservations = reservations
        self._guests = guests
        self._cleaning = cleaning
        self._incidents = incidents
        self._approvals = approvals
        self._expenses = expenses

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        role: UserRole,
        locale: Locale,
        today: date,
    ) -> PropertyDetail:
        property = await self._properties.get(tenant_id, property_id)
        if property is None:
            # R2.2: the same answer for "does not exist" and "belongs to another tenant",
            # because the port cannot tell them apart either (design D11).
            raise PropertyNotFoundError("Property does not exist")

        may_read_reservations = is_allowed(role, Permission.READ_RESERVATIONS)
        may_read_cleaning = is_allowed(role, Permission.READ_CLEANING_TASKS)
        may_read_access = is_allowed(role, Permission.READ_ACCESS_RECORDS)

        # **The stay is read when EITHER permission needs it**, and that is not laziness.
        # `access_status` is a column of `reservations` (the projection
        # `AccessRecordRepository.save` maintains), so the access block cannot be built
        # without the stay. Gating the read on `READ_RESERVATIONS` alone made
        # `READ_ACCESS_RECORDS` useless without it — which R2.7 does not say, since it lists
        # the three permissions as independent gates. The QA panel of sections 6-7 found it
        # by inventing a role with one and not the other; no such role exists today, and the
        # point of fixing it now is that none ever has to.
        #
        # Each block is still gated on its own permission below: reading the row is not the
        # same as publishing it.
        reservation: Reservation | None = None
        guests_by_id: dict[uuid.UUID, object] = {}
        if may_read_reservations or may_read_access:
            reservations = await self._reservations.list_for_properties(
                tenant_id,
                [property_id],
                today,
                today + timedelta(days=RESERVATION_LOOKAHEAD_DAYS),
            )
            reservation = _current_or_next_per_property(reservations, today).get(property_id)
            # The guest, unlike the stay, is only ever needed by the reservation block.
            if (
                may_read_reservations
                and reservation is not None
                and reservation.guest_id is not None
            ):
                guests_by_id = {
                    guest.id: guest
                    for guest in await self._guests.list_for_ids(
                        tenant_id, [reservation.guest_id]
                    )
                }

        cleaning: CleaningTaskSummary | None = None
        if may_read_cleaning:
            cleaning = _one_live_task_per_property(
                await self._cleaning.list_live_for_properties(tenant_id, [property_id])
            ).get(property_id)

        incidents = await self._incidents.list_open_for_property(tenant_id, property_id)
        approvals = await self._approvals.list_pending_for_property(tenant_id, property_id)
        financial = await self._expenses.summary_for_property(tenant_id, property_id)

        guest = guests_by_id.get(reservation.guest_id) if reservation is not None and reservation.guest_id else None

        return PropertyDetail(
            property_id=property.id,
            property_code=property.internal_code,
            operational_state=property.current_operational_state,
            current_or_next_reservation=(
                _reservation_block(reservation, guests_by_id)
                if may_read_reservations and reservation is not None
                else None
            ),
            # The guest rides with the reservation, so it is gated by the same permission
            # (D10: "`READ_RESERVATIONS` → reserva y huésped").
            guest=(
                GuestBlock(name=getattr(guest, "full_name", None))
                if may_read_reservations and guest is not None
                else None
            ),
            access=(
                AccessBlock(
                    label=ACCESS_STATUS_LABELS.render(reservation.access_status.value, locale)
                )
                if may_read_access and reservation is not None
                else None
            ),
            cleaning_status=(
                CLEANING_STATUS_LABELS.render(cleaning.status.value, locale)
                if may_read_cleaning and cleaning is not None
                else None
            ),
            last_cleaning_photos=_NO_CLEANING_PHOTOS,
            open_incidents=tuple(
                IncidentBlock(
                    id=incident.id,
                    # From the category, never from `incidents.title`: the stored title is
                    # free text in whatever language it was typed, so it could not satisfy
                    # the `LocalizedText` contract even if it were safe to publish.
                    title=INCIDENT_TITLE_LABELS.render(incident.category.value, locale) or "",
                    severity=incident.severity,
                    opened_at=incident.opened_at,
                )
                for incident in incidents
            ),
            # The pending expenses are `statements`' own and no permission of `reservations`
            # gates them, but the stay's currency and gross amount are the stay's. Passing
            # the reservation here unconditionally published `reservation_total` to a role
            # holding `READ_ACCESS_RECORDS` and not `READ_RESERVATIONS` — the one that `:273`
            # reads the row for — while `current_or_next_reservation` came back `null` to the
            # same caller. That is precisely the "agregar no concede" D10 exists to prevent,
            # so the block is built from the expenses alone when the permission is absent.
            financial=_financial_block(
                reservation if may_read_reservations else None,
                financial.pending_expenses,
            ),
            # The operator-facing note. `access_notes`, `cleaning_notes` and
            # `emergency_notes` are deliberately NOT here: `property_admin.py` records that
            # "an operator can paste a door code or a wifi key into 'access notes'", which
            # makes all three rule-11 sinks. PRD §9.2's "notas" gets no column of its own
            # until something owns it, and inventing one from a sink is not the way.
            notes=None,
            pending_approvals=tuple(
                ApprovalBlock(
                    id=approval.id,
                    label=APPROVAL_LABELS.render(approval.related_type.value, locale) or "",
                    amount=approval.amount,
                    currency=DEFAULT_CURRENCY,
                )
                for approval in approvals
            ),
        )


class GetOperationalKpisUseCase:
    """`GET /api/v1/dashboard/operational-kpis` (`dashboard-operational-kpis` R1, R2, R3).

    Three tenant-wide counts, each gated on the permission that protects its source
    domain (design D4): a role lacking a source's permission gets `None` for that field
    and the query is **skipped entirely**, not run and then discarded — a role holding
    none of the three costs zero domain queries.
    """

    def __init__(
        self,
        *,
        cleaning: CleaningTaskRepository,
        reservations: ReservationRepository,
        incidents: IncidentReader,
    ) -> None:
        self._cleaning = cleaning
        self._reservations = reservations
        self._incidents = incidents

    async def execute(
        self, *, tenant_id: uuid.UUID, role: UserRole, today: date
    ) -> OperationalKpis:
        cleanings_today = (
            await self._cleaning.count_live_for_day(tenant_id, today)
            if is_allowed(role, Permission.READ_CLEANING_TASKS)
            else None
        )
        upcoming_checkins = (
            await self._reservations.count_check_ins_in_range(
                tenant_id, today, today + timedelta(days=UPCOMING_CHECKIN_WINDOW_DAYS)
            )
            if is_allowed(role, Permission.READ_RESERVATIONS)
            else None
        )
        open_incidents = (
            _open_incident_counts_block(await self._incidents.count_open_for_tenant(tenant_id))
            if is_allowed(role, Permission.READ_INCIDENTS)
            else None
        )
        return OperationalKpis(
            cleanings_today=cleanings_today,
            upcoming_checkins=upcoming_checkins,
            open_incidents=open_incidents,
        )


def _open_incident_counts_block(counts: OpenIncidentCounts) -> OpenIncidentCountsBlock:
    return OpenIncidentCountsBlock(total=counts.total, urgent=counts.urgent)


def _current_or_next_per_property(
    reservations: Sequence[Reservation], today: date
) -> dict[uuid.UUID, Reservation]:
    """The stay to show per property: the one in progress, else the soonest to come.

    Grouping in memory rather than in SQL is what keeps the query count fixed (D2). Ordered
    by `check_in_date` then `id` so two stays starting the same day resolve the same way on
    every request.
    """
    chosen: dict[uuid.UUID, Reservation] = {}
    for reservation in sorted(
        reservations, key=lambda item: (item.check_in_date, str(item.id))
    ):
        if reservation.check_out_date < today:
            continue
        chosen.setdefault(reservation.property_id, reservation)
    return chosen


def _one_live_task_per_property(
    tasks: Sequence[CleaningTaskSummary],
) -> dict[uuid.UUID, CleaningTaskSummary]:
    """One live cleaning task per property, deterministically.

    A property should have at most one live task — `uq_cleaning_tasks_live_reservation`
    enforces it per reservation — but "at most one per property" is not a constraint the
    schema carries, so the tie is broken by id rather than left to row order.
    """
    chosen: dict[uuid.UUID, CleaningTaskSummary] = {}
    for task in sorted(tasks, key=lambda item: str(item.id)):
        chosen.setdefault(task.property_id, task)
    return chosen


def _reservation_block(
    reservation: Reservation, guests_by_id: Mapping[uuid.UUID, object]
) -> ReservationBlock:
    guest = guests_by_id.get(reservation.guest_id) if reservation.guest_id else None
    return ReservationBlock(
        id=reservation.id,
        reference=_reference(reservation),
        guest_name=getattr(guest, "full_name", None),
        check_in=reservation.check_in_date,
        check_out=reservation.check_out_date,
    )


def _reference(reservation: Reservation) -> str | None:
    """"Booking.com #1234" — what an operator recognises (`dto.ts:71`)."""
    channel = reservation.channel.value
    if not reservation.external_pms_id:
        return channel
    return f"{channel} #{reservation.external_pms_id}"


def _next_action_block(state, locale: Locale) -> NextActionBlock | None:
    action = next_action_for(state)
    if action is None:
        return None
    label = NEXT_ACTION_LABELS.render(action.action_key, locale)
    if label is None:
        # The catalogue is exhaustive over the table and a test enforces it, so this is the
        # future-proofing branch rather than a live path: no label means no claim.
        return None
    return NextActionBlock(
        label=label,
        responsible=(
            RESPONSIBLE_LABELS.render(action.responsible.value, locale)
            if action.responsible is not None
            else None
        ),
    )


def _financial_block(
    reservation: Reservation | None, pending: Mapping[str, Decimal]
) -> FinancialBlock:
    """Unwraps the reservation and defers the rule to `domain/`.

    The rule itself — what a currency figure means when the data does not agree — lives in
    `app/dashboard/domain/financials.py`. The architect panel of section 6 was right that
    it had no business here: `steering/backend-architecture.md` puts "Reglas de negocio
    propias (si hay una regla, pertenece a `domain/`)" among the things `application/` must
    not contain. What is left in this layer is the unwrapping, which is orchestration.
    """
    return financial_block(
        reservation_currency=reservation.currency if reservation is not None else None,
        reservation_total=reservation.gross_amount if reservation is not None else None,
        pending_expenses=pending,
    )
