"""`python -m app.integrations.cli.pms_sync` — pull reservations from the PMS (R3, design D10).

A console command, not an HTTP endpoint: PRD §23 defines no sync endpoint, and the natural
trigger is Celery beat, which belongs to the `celery-jobs` roadmap entry. When that arrives it
schedules `SyncReservationsFromPmsUseCase` directly — this command exists so the capability is
operable (and verifiable) before then, exactly like `app/cli/bootstrap.py` does for the seed.

Takes the tenant as an argument because a command has no token to derive it from. That is the
one place in the system where a tenant id comes from outside a request, and it is deliberate:
an operator running a sync says which tenant they mean.
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

# Imported for its side effect, exactly as `app/main.py` does it: every model module must be
# registered before the first query, or SQLAlchemy cannot resolve the foreign keys between
# tables it has not seen (`guests.tenant_id → tenants.id` is the first one to blow up).
# A command has its own import graph, so it needs this on its own — the test suite's conftest
# imports the registry for every test, which is why no unit test can catch its absence here.
# This was found by running the command by hand.
import app.core.models_registry  # noqa: F401
from app.core.db import async_session_factory, bind_session_to_tenant
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.ingest import IngestReport
from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
from app.integrations.infrastructure.mock_pms import MockPMSAdapter
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

DEFAULT_WINDOW_DAYS = 30
USAGE = "usage: python -m app.integrations.cli.pms_sync <tenant-uuid> [window-days]"


async def run(tenant_id: uuid.UUID, *, window_days: int = DEFAULT_WINDOW_DAYS) -> IngestReport:
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        # Marks the session so the listener of `app/core/db.py` also scopes ORM reads: a
        # command does not go through `get_authenticated_request`, which is what normally
        # does this (limit 2 of the listener's docstring).
        bind_session_to_tenant(session, tenant_id)
        use_case = SyncReservationsFromPmsUseCase(
            pms=MockPMSAdapter(),
            reservations=SqlAlchemyReservationRepository(session),
            properties=SqlAlchemyPropertyRepository(session),
            guests=SqlAlchemyGuestRepository(session),
            timeline=SqlAlchemyTimelineEventRepository(session),
            uow=SqlAlchemyUnitOfWork(session),
        )
        return await use_case.execute(
            tenant_id=tenant_id,
            since=now - timedelta(days=window_days),
            now=now,
        )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        tenant_id = uuid.UUID(args[0])
    except ValueError:
        print(f"pms-sync: {args[0]!r} is not a UUID\n{USAGE}", file=sys.stderr)
        return 2
    window_days = DEFAULT_WINDOW_DAYS
    if len(args) > 1:
        try:
            window_days = int(args[1])
        except ValueError:
            print(f"pms-sync: window-days must be an integer\n{USAGE}", file=sys.stderr)
            return 2

    report = asyncio.run(run(tenant_id, window_days=window_days))
    print(
        f"pms-sync: created {report.created}, updated {report.updated}, "
        f"skipped {report.skipped}"
    )
    for error in report.errors:
        # Reported, not swallowed: a row the sync could not import is operational
        # information, and R3.4 requires it to survive the run.
        print(f"pms-sync: skipped {error.reference} — {error.reason}", file=sys.stderr)
    # Skipped rows are not a failure of the command: the run did what it could, which is the
    # whole point of R3.4. Only an unhandled exception makes this non-zero.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
