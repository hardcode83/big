"""PostgreSQL implementation of the guest email exclusion port."""

import hashlib
import logging
import time
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.guests.domain.ports import GuestEmailExclusion
from app.guests.domain.value_objects import normalize_email

logger = logging.getLogger(__name__)


def guest_email_lock_key(tenant_id: uuid.UUID, normalized_email: str) -> int:
    """Return the stable signed int64 advisory-lock key required by R3."""
    payload = (f"{tenant_id}" + chr(0) + normalize_email(normalized_email)).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class PostgresGuestEmailExclusion(GuestEmailExclusion):
    """Acquire a transaction-scoped advisory lock on the caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire(self, tenant_id: uuid.UUID, normalized_email: str) -> None:
        if not normalized_email:
            return
        started = time.perf_counter()
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": guest_email_lock_key(tenant_id, normalized_email)},
        )
        # Technical-only telemetry: the key, tenant and contact values are intentionally
        # absent so lock contention can be diagnosed without logging Guest PII.
        logger.debug(
            "guest email exclusion acquired",
            extra={"wait_seconds": time.perf_counter() - started},
        )
