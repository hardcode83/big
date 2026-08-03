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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import async_session_factory, bind_session_to_tenant
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.ingest import IngestReport, RowError
from app.integrations.application.use_cases import SyncReservationsFromPmsUseCase
from app.integrations.domain.errors import PmsUnavailableError
from app.integrations.domain.ports import PMSAdapter
from app.integrations.infrastructure.channex.adapter import ChannexAdapter
from app.integrations.infrastructure.channex.client import ChannexClient
from app.integrations.infrastructure.mock_pms import MockPMSAdapter
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.tenants.infrastructure.models import TenantModel
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

DEFAULT_WINDOW_DAYS = 30
MOCK_PROVIDER = "mock"
CHANNEX_PROVIDER = "channex"
PROVIDERS = (MOCK_PROVIDER, CHANNEX_PROVIDER)
USAGE = (
    "usage: python -m app.integrations.cli.pms_sync <tenant-uuid> [window-days] "
    f"[--provider {{{','.join(PROVIDERS)}}}]"
)


def build_adapter(provider: str) -> PMSAdapter:
    """Resolve the PMS adapter for this run (R3, design D3).

    **A stopgap, and deliberately a small one.** [ADR 0006](../../../../docs/adr/0006-pms-channel-manager-provider.md)
    retired PRD §22's global `PMS_PROVIDER` in favour of resolving the provider **per
    property**, with credentials stored encrypted on `Property`. That is
    `pms-beds24-adapter`'s job, and it replaces this function with a `PMSAdapterFactory`.

    Which is exactly why the choice lives in a command-line flag and not in `Settings`: a flag
    on an operator's command cannot leak into the application or the test suite, and it does
    not resurrect a configuration name that a later reader would mistake for the real
    mechanism. `mock` stays the default, so nothing changes for anyone who does not ask.
    """
    if provider == MOCK_PROVIDER:
        return MockPMSAdapter()
    if provider == CHANNEX_PROVIDER:
        if not settings.channex_api_key.strip():
            # Refuses to start rather than falling back to the mock (R3.2). A silent fallback
            # would report "created 0, updated 0" — indistinguishable from a real empty sync,
            # which is the worst possible outcome for a misconfigured credential.
            raise PmsUnavailableError(
                "CHANNEX_API_KEY is not set; refusing to run a Channex sync against no "
                "credentials (set it in .env, see .env.example)"
            )
        return ChannexAdapter(
            ChannexClient(
                api_key=settings.channex_api_key,
                base_url=settings.channex_base_url,
                max_pages=settings.channex_max_pages,
                page_limit=settings.channex_page_limit,
                timeout=settings.channex_timeout_seconds,
            )
        )
    raise ValueError(f"Unknown PMS provider {provider!r}")


class UnknownTenantError(RuntimeError):
    """The tenant argument names no tenant.

    Exists so a typo in the UUID does not look like a successful run: without it, every row was
    reported "Unknown property for this tenant" and the command exited 0 — indistinguishable from
    "the PMS had nothing for us". Raised by `run`, reported as exit code 2 by `main`. Found by the
    feature-scale QA review.
    """


async def sync_with_session(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
    provider: str = MOCK_PROVIDER,
) -> IngestReport:
    """The command's actual work, against a session somebody else owns.

    Split out from `run` so the suite can exercise it on the test session: `run` opens its own
    session from `async_session_factory`, and a test that awaited that would hit the
    "attached to a different loop" problem `tests/conftest.py` documents at length.
    """
    at = now or datetime.now(UTC)
    # Marks the session so the listener of `app/core/db.py` also scopes ORM reads: a command does
    # not go through `get_authenticated_request`, which is what normally does this (limit 2 of the
    # listener's docstring).
    bind_session_to_tenant(session, tenant_id)
    if await session.scalar(select(TenantModel.id).where(TenantModel.id == tenant_id)) is None:
        raise UnknownTenantError(f"No tenant with id {tenant_id}")
    adapter = build_adapter(provider)
    use_case = SyncReservationsFromPmsUseCase(
        pms=adapter,
        reservations=SqlAlchemyReservationRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
    report = await use_case.execute(
        tenant_id=tenant_id,
        since=at - timedelta(days=window_days),
        now=at,
    )
    # Rows the adapter could not even turn into a DTO fold into the report's skipped count and
    # errors, so the command reports them like any other unusable row.
    #
    # Plain attribute access, not `getattr(..., [])`. The default was the bug: an adapter that
    # simply did not define the attribute would report **zero** unmappable rows while dropping
    # some, silently. `unmappable_rows` is now declared on `PMSAdapter` so every implementation
    # owes it — see that docstring for why widening the return type is the real fix and why it
    # belongs to `pms-beds24-adapter`.
    for reason in adapter.unmappable_rows:
        report.skipped += 1
        report.errors.append(RowError(reason=f"provider row could not be mapped: {reason}"))
    return report


async def run(
    tenant_id: uuid.UUID,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    provider: str = MOCK_PROVIDER,
) -> IngestReport:
    async with async_session_factory() as session:
        return await sync_with_session(
            session, tenant_id, window_days=window_days, provider=provider
        )


def _extract_provider(args: list[str]) -> tuple[list[str], str]:
    """Pull `--provider` out of argv, leaving the positional arguments untouched.

    Hand-rolled rather than `argparse` to keep the existing positional contract and its exact
    error messages, which `tests/integrations/test_pms_sync_cli.py` already pins.
    """
    provider = MOCK_PROVIDER
    remaining: list[str] = []
    index = 0
    while index < len(args):
        argument = args[index]
        if argument.startswith("--provider="):
            provider = argument.removeprefix("--provider=")
        elif argument == "--provider":
            if index + 1 >= len(args):
                raise ValueError("--provider needs a value")
            provider = args[index + 1]
            index += 1
        else:
            remaining.append(argument)
        index += 1
    if provider not in PROVIDERS:
        # The rejected value is NOT echoed (R2.3). `--provider=<pasted-api-key>` is a plausible
        # fumble, and printing it would put the credential in a terminal transcript or a CI log
        # on top of the shell history. `channex_probe.py` already took this posture for the same
        # reason; the security panel caught that this path had not.
        raise ValueError(f"unknown provider (value not echoed); accepted: {', '.join(PROVIDERS)}")
    return remaining, provider


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        args, provider = _extract_provider(raw)
    except ValueError as error:
        print(f"pms-sync: {error}\n{USAGE}", file=sys.stderr)
        return 2
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

    try:
        report = asyncio.run(run(tenant_id, window_days=window_days, provider=provider))
    except UnknownTenantError as error:
        print(f"pms-sync: {error}", file=sys.stderr)
        return 2
    except PmsUnavailableError as error:
        # A provider that could not answer is not an empty sync, and the exit code has to say
        # so — this is the whole reason the port gained an error contract (design D5).
        print(f"pms-sync: {error}", file=sys.stderr)
        return 3
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
