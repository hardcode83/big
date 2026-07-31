"""Ingest use cases: PMS sync and CSV import (R3, R4, design D9, D10, D11).

Both are one business operation and one transaction: they build the rows, hand them to
`ReservationIngestor`, and commit once at the end (design D4). A per-row commit would leave a
half-imported file behind on the first infrastructure failure, and the report would then
describe a state nobody can reconstruct.
"""

import uuid
from datetime import datetime

from app.core.unit_of_work import UnitOfWork
from app.guests.domain.repositories import GuestRepository
from app.integrations.application.ingest import IngestReport, ReservationIngestor
from app.integrations.domain.dtos import ReservationDTO
from app.integrations.domain.ports import PMSAdapter
from app.properties.domain.entities import Property
from app.properties.domain.repositories import PropertyRepository
from app.reservations.domain.repositories import ReservationRepository
from app.timeline.domain.enums import TimelineActorType
from app.timeline.domain.repositories import TimelineEventRepository

PMS_SOURCE = "pms"
CSV_SOURCE = "csv"


class SyncReservationsFromPmsUseCase:
    """Pull reservations from the PMS into this tenant (R3).

    The actor of the timeline events is `SYSTEM`: a command or, later, Celery beat runs this,
    and there is no person to attribute it to (design D15).
    """

    def __init__(
        self,
        *,
        pms: PMSAdapter,
        reservations: ReservationRepository,
        properties: PropertyRepository,
        guests: GuestRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._pms = pms
        self._properties = properties
        self._ingestor = ReservationIngestor(
            reservations=reservations, guests=guests, timeline=timeline
        )
        self._uow = uow

    async def execute(
        self, *, tenant_id: uuid.UUID, since: datetime, now: datetime
    ) -> IngestReport:
        rows = await self._pms.list_reservations(since)

        async def resolve(row: ReservationDTO) -> Property | None:
            # By `pms_external_id`, the mapping the provider knows about (design D16). A row
            # whose external id is ambiguous within the tenant raises a domain error, which
            # the ingestor turns into a reported row rather than an aborted run.
            return await self._properties.find_by_pms_external_id(
                tenant_id, row.property_external_id
            )

        report = await self._ingestor.ingest(
            tenant_id=tenant_id,
            rows=rows,
            resolve_property=resolve,
            now=now,
            actor_type=TimelineActorType.SYSTEM,
            actor_user_id=None,
            source=PMS_SOURCE,
        )
        await self._uow.commit()
        return report


class ImportReservationsFromCsvUseCase:
    """Import reservations from an uploaded CSV (R4).

    The actor is `USER` with the uploader's id: unlike the sync, there IS a person behind
    this, and the timeline has to be able to answer who imported what (design D15).
    """

    def __init__(
        self,
        *,
        reservations: ReservationRepository,
        properties: PropertyRepository,
        guests: GuestRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._properties = properties
        self._ingestor = ReservationIngestor(
            reservations=reservations, guests=guests, timeline=timeline
        )
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        rows: list[ReservationDTO],
        now: datetime,
    ) -> IngestReport:
        async def resolve(row: ReservationDTO) -> Property | None:
            # By `internal_code` (REDES11), because a person fills in this file and does not
            # know UUIDs (design D11). It is also why a CSV can never name a property of
            # another tenant: the lookup is scoped.
            return await self._properties.find_by_internal_code(
                tenant_id, row.property_external_id
            )

        report = await self._ingestor.ingest(
            tenant_id=tenant_id,
            rows=rows,
            resolve_property=resolve,
            now=now,
            actor_type=TimelineActorType.USER,
            actor_user_id=actor_user_id,
            source=CSV_SOURCE,
        )
        await self._uow.commit()
        return report
