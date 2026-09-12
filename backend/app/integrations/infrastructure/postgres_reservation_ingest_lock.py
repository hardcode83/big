"""PostgreSQL implementation of the reservation ingest lock port (review finding 1).

Mirrors `app.guests.infrastructure.postgres_guest_email_exclusion.PostgresGuestEmailExclusion`
exactly: same `pg_advisory_xact_lock` call (transaction-scoped, released automatically at
commit/rollback, no lock table, no explicit release), same telemetry-without-PII logging
pattern. That file already solves the identical class of problem — concurrent writers racing on
the same logical resource — for guest email resolution; this reuses the idiom for the identity
that decides create-vs-update in `ReservationIngestor`: `(tenant_id, external_pms_id)`.
"""

import hashlib
import logging
import time
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.domain.ports import ReservationIngestLock

logger = logging.getLogger(__name__)


def reservation_ingest_lock_key(tenant_id: uuid.UUID, external_pms_id: str) -> int:
    """Return the stable signed int64 advisory-lock key for one tenant/PMS-booking pair."""
    payload = (f"{tenant_id}" + chr(0) + external_pms_id).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class PostgresReservationIngestLock(ReservationIngestLock):
    """Acquire a transaction-scoped advisory lock on the caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire(self, tenant_id: uuid.UUID, external_pms_id: str) -> None:
        if not external_pms_id:
            return
        started = time.perf_counter()
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": reservation_ingest_lock_key(tenant_id, external_pms_id)},
        )
        # Technical-only telemetry: the key, tenant and external id are intentionally absent so
        # lock contention can be diagnosed without logging any PMS-side booking identity.
        logger.debug(
            "reservation ingest lock acquired",
            extra={"wait_seconds": time.perf_counter() - started},
        )
