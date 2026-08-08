"""Wiring for the integration endpoints (design D1)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.config import settings
from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.core.redis import get_redis
from app.integrations.application.use_cases import (
    CreateWebhookEndpointUseCase,
    ImportReservationsFromCsvUseCase,
    RotateWebhookEndpointUseCase,
)
from app.integrations.application.webhooks import ReceiveWebhookUseCase
from app.integrations.infrastructure.card_data import scrub_card_data
from app.integrations.infrastructure.csv_parser import CsvReservationParser
from app.integrations.infrastructure.repositories import (
    SqlAlchemyWebhookEndpointRepository,
    SqlAlchemyWebhookEventRepository,
)
from app.integrations.infrastructure.throttle import RedisWebhookThrottle
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_import_csv_use_case(session: SessionDep) -> ImportReservationsFromCsvUseCase:
    return ImportReservationsFromCsvUseCase(
        parser=CsvReservationParser(),
        max_rows=settings.csv_import_max_rows,
        reservations=SqlAlchemyReservationRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_webhook_throttle() -> RedisWebhookThrottle:
    """The two limits of D6, built from configuration on every request.

    Reads `settings` here rather than closing over the values at import time, so the same
    reasoning `MaxBodySizeMiddleware`'s callable provider records applies: an operator changing a
    limit does not have to rebuild the application, and a test can move it without reimporting.
    """
    return RedisWebhookThrottle(
        get_redis(),
        deliveries_per_minute=settings.webhook_rate_limit_per_minute,
        probes_per_minute=settings.webhook_probe_limit_per_minute,
    )


def get_receive_webhook_use_case(session: SessionDep) -> ReceiveWebhookUseCase:
    """Wires the receiver, including the card-data scrubber it will not import itself.

    `scrub_card_data` is supplied here because `application/` may not reach a concrete adapter
    (`tests/test_layering.py`). This is the composition root for that dependency, and the ONLY
    place it is chosen — which is what makes "the receiver always scrubs" a property of the
    wiring rather than of each caller remembering.
    """
    return ReceiveWebhookUseCase(
        endpoints=SqlAlchemyWebhookEndpointRepository(session),
        events=SqlAlchemyWebhookEventRepository(session),
        scrub=scrub_card_data,
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_create_webhook_endpoint_use_case(
    session: SessionDep,
) -> CreateWebhookEndpointUseCase:
    return CreateWebhookEndpointUseCase(
        endpoints=SqlAlchemyWebhookEndpointRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_rotate_webhook_endpoint_use_case(
    session: SessionDep,
) -> RotateWebhookEndpointUseCase:
    return RotateWebhookEndpointUseCase(
        endpoints=SqlAlchemyWebhookEndpointRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
