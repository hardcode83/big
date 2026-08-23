"""Wiring for the integration endpoints (design D1)."""

from functools import partial
from collections.abc import Callable
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
from app.integrations.domain.storage import FileStorageFactory, derive_signing_key
from app.integrations.infrastructure.storage import (
    ConfiguredFileStorageFactory,
    build_s3_client,
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


# --- shared object-storage wiring (`incident-photos` section 7) -----------------------
#
# Moved here from `app/cleaning/api/dependencies.py` when `maintenance` became the second
# consumer. Both are needed by every domain that stores or serves a photo, and neither has
# anything to do with cleaning: `get_url_signing_key` derives from `JWT_SECRET_KEY`, and
# `get_file_storage_factory` is the one place the object-store settings are read.
#
# Living in `app/integrations/api/` rather than being imported across from `cleaning/api/`
# keeps the import direction the one this repository already uses for shared storage code —
# the same direction `cleaning/api/photos_router.py` takes to reach `signed_media.py`. A
# sideways `maintenance/api -> cleaning/api` import would have been the alternative, and the
# section 6 architecture panel named that shape as the one to avoid.

def get_url_signing_key() -> bytes:
    """The HKDF-derived URL signing key of design D6.

    Its own dependency because **two** things need the same bytes and must not drift: the
    factory below, which signs, and `ServeSignedObjectUseCase`, which verifies. Deriving
    it twice from `settings` would work, but it would also let a test override one half and
    silently leave the other on the real secret — every signature would then be refused, and
    the failure would look like a broken signing scheme rather than like a broken fixture.

    The key is derived per call rather than cached. It is two HMACs of a 32-byte input, and a
    module-level cache of a value computed from `JWT_SECRET_KEY` is the kind of thing that
    survives a settings change in a test and then explains nothing when a signature stops
    verifying. `derive_signing_key` is pure, so calling it is the cheap option and the honest
    one.
    """
    return derive_signing_key(settings.jwt_secret_key)


SigningKeyDep = Annotated[bytes, Depends(get_url_signing_key)]


def storage_factory_for(url_prefix: str) -> Callable[[bytes], FileStorageFactory]:
    """Build the `FileStorageFactory` dependency for one consumer's signed-URL prefix.

    **A builder rather than a single shared dependency, because the prefix is per-consumer and
    the signing key is not.** `LocalFileStorage.signed_url` mints
    `{url_prefix}/{object id}?exp=…&sig=…`, and each domain serves its objects from its own
    anonymous route — `/api/v1/cleaning-photos` and `/api/v1/incident-photos`. A single shared
    dependency would hand every consumer `DEFAULT_SIGNED_URL_PREFIX`, i.e. cleaning's route,
    which then cannot resolve another domain's object id: the URL verifies against a key the
    other table does not have, so it answers the constant `403` and looks like a broken
    signature.

    Found by `incident-photos` section 8, whose serving tests failed exactly that way. Design
    D10 said to "reuse" this dependency and design D5 said `FileStorageFactory` is not touched;
    both still hold — the class and every port are unchanged, and what varies is one
    constructor argument the class already accepted. Recorded as a D10 clarification, approved
    by Jose on 2026-08-22.

    **This is the only place the object-store settings are read** (`object-storage-provisioning`
    design D5, R3.2): the use cases receive the factory and never learn a bucket, a region or
    an endpoint exists. `partial` keeps `s3_client_factory` a zero-argument callable, so the
    tests that inject a spy through a consumer's dependency go on working unchanged.

    `.strip() or None` is what satisfies R3.4: an unset variable arrives as `""`, and boto3
    reads an empty `endpoint_url` as an endpoint rather than as its absence. Turning it into
    `None` is what makes "point at AWS" mean *configure nothing*.

    The `.strip()` is not decoration, and a bare `or None` was wrong here. A whitespace-only
    value — one stray space surviving a hand-edited `.env` — is truthy, so it would reach
    `boto3.client(...)` and raise `InvalidRegionError` or `ValueError: Invalid endpoint:`
    straight out of `storage_for(S3)`, bypassing the `StorageWriteError` contract that
    `ConfiguredFileStorageFactory` otherwise guarantees for a misconfigured store. The bucket
    beside it has always been read as `s3_bucket.strip()` for exactly this reason.
    """

    def _factory(signing_key: SigningKeyDep) -> FileStorageFactory:
        return ConfiguredFileStorageFactory(
            signing_key=signing_key,
            url_prefix=url_prefix,
            s3_bucket=settings.s3_bucket,
            s3_client_factory=partial(
                build_s3_client,
                region_name=settings.s3_region.strip() or None,
                endpoint_url=settings.s3_endpoint_url.strip() or None,
            ),
        )

    return _factory
