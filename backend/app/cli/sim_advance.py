"""Advance property states for one tenant (change `sim-advance` R1, R3; design D2-D5).

Runs the three clock triggers for one tenant, in order, each in its own marked
session and commit, sharing the same frozen `now`. Operator entry point:

    python -m app.cli.sim_advance --tenant <uuid> [--at <iso>]

**Deliberately not a Celery task** (D2). Importing `scheduler/tasks.py` would drag
Celery into the CLI graph; the wiring is one function long, so the file carries its
own copy, anchored to the canonical source by a comment.

**No infrastructure added** (`steering/architecture.md`): reuses
`AdvancePropertyStatesUseCase` and `worker_session_factory()` as-is. New CLI lives
under `app/cli/`, nothing more.

The env guard at D5 fires before any DB session is opened (rule 8 of
`steering/security.md`): a deploy that wires this command into `cron` must NOT have
it fire against staging or production. `local`/`dev` only.
"""

import argparse
import asyncio
import logging
import sys
import typing
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

# Imported for its side effect, exactly as `app/main.py`, `app/scheduler/runner.py`
# and `app/cli/seed_demo.py` do it: a CLI has its own import graph, and SQLAlchemy
# cannot resolve cross-table foreign keys for models it has never seen.
import app.core.models_registry  # noqa: F401

from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.application.use_cases import ProvisionCleaningTaskUseCase
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningTaskRepository,
)
from app.core.config import settings
from app.core.db import bind_session_to_tenant
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.properties.application.use_cases import AdvancePropertyStatesUseCase, AdvanceReport
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.scheduler.runner import worker_session_factory
from app.tenants.infrastructure.models import TenantModel
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository


logger = logging.getLogger(__name__)


# R1: order is binding. Each entry maps a Celery job name to its trigger so the
# report line carries the operator-recognisable label that already exists in
# `scheduler/schedule.py::CADENCES`.
_CLOCK_JOBS: tuple[tuple[str, PropertyStateTrigger], ...] = (
    ("check_checkin_windows", PropertyStateTrigger.CHECKIN_WINDOW_OPENED),
    ("mark_occupied_estimated", PropertyStateTrigger.CHECKIN_TIME_REACHED),
    ("process_checkouts", PropertyStateTrigger.CHECKOUT_TIME_REACHED),
)

_ALLOWED_ENVIRONMENTS: frozenset[str] = frozenset({"local", "dev"})


class _Parser(argparse.ArgumentParser):
    """Argparse that exits with code 1 on argument errors (R1, task 2.1).

    The default exits with code 2; the verification of this command expects 1 for
    a bad `--tenant` or a naive `--at`.
    """

    def error(self, message: str) -> typing.NoReturn:
        self.print_usage(sys.stderr)
        print(f"sim_advance: {message}", file=sys.stderr)
        raise SystemExit(1)


def _parse_tenant(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise argparse.ArgumentTypeError(f"invalid UUID {value!r}: {exc}") from exc


def _parse_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid ISO 8601 instant {value!r}: {exc}"
        ) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"naive datetime not accepted (D3 — must include a UTC offset, e.g. "
            f"'...+00:00' or '...Z'); got {value!r}"
        )
    return parsed.astimezone(UTC)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="python -m app.cli.sim_advance",
        description=(
            "Advance property state clock triggers for one tenant, in dev/local. "
            "Runs CHECKIN_WINDOW_OPENED, CHECKIN_TIME_REACHED and "
            "CHECKOUT_TIME_REACHED in order, each in its own marked session and "
            "commit, sharing the resolved `--at` (or `datetime.now(UTC)`)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Two traps with --at (R1.8):\n"
            "  1. --at is clamped to a window around each reservation's stay: at most 30\n"
            "     days BEFORE check-in/check-out and at most 2 days AHEAD of it. An --at\n"
            "     outside that window simply finds no candidate for that reservation.\n"
            "  2. \"today\" is evaluated in the PROPERTY's own local timezone, not UTC. An\n"
            "     --at at 23:00 UTC the day before check-in will NOT open the check-in\n"
            "     window even if it is already \"today\" in UTC, if the property's local\n"
            "     date has not rolled over yet."
        ),
    )
    parser.add_argument(
        "--tenant",
        required=True,
        type=_parse_tenant,
        help="Tenant UUID (required).",
    )
    parser.add_argument(
        "--at",
        type=_parse_at,
        default=None,
        metavar="ISO8601",
        help=(
            "Synthetic `now` as an ISO 8601 instant with a UTC offset "
            "(e.g. 2026-09-10T12:00:00+00:00). Naive datetimes are rejected. "
            "Defaults to `datetime.now(UTC)` if omitted."
        ),
    )
    return parser


async def _advance(
    session,
    tenant_id: uuid.UUID,
    now: datetime,
    *,
    trigger: PropertyStateTrigger,
) -> AdvanceReport:
    """One clock trigger for one tenant (R1).

    Copied from scheduler/tasks.py:143-157 to keep the Celery graph out of the CLI
    import path. The wiring — repositories built from the session, provisioner
    only for the checkout trigger, `SqlAlchemyUnitOfWork(session)` so the use
    case commits its own transaction — must not drift from the canonical source.
    The provisioner construction is the literal copy of
    `seed_demo._advance_states:1615-1628`.
    """
    provisioner = (
        ProvisionCleaningTaskUseCase(
            tasks=SqlAlchemyCleaningTaskRepository(session),
            templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
            configs=SqlAlchemyTenantConfigRepository(session),
            users=SqlAlchemyUserRepository(session),
            transitions=SqlAlchemyPropertyStateTransitionRepository(session),
            timeline=SqlAlchemyTimelineEventRepository(session),
            properties=SqlAlchemyPropertyRepository(session),
            notifications=SqlAlchemyNotificationLogRepository(session),
        )
        if trigger is PropertyStateTrigger.CHECKOUT_TIME_REACHED
        else None
    )
    use_case = AdvancePropertyStatesUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
        provisioner=provisioner,
    )
    return await use_case.execute(tenant_id=tenant_id, trigger=trigger, now=now)


async def _tenant_exists(tenant_id: uuid.UUID) -> bool:
    """Read tenants on an UNMARKED session (R1: refuse if the tenant does not exist).

    `tenants` carries no `tenant_id`, so the global filter never touches it; we
    still open this on a never-marked session for the same reason
    `app/scheduler/runner.py::list_active_tenants` does — the invariant
    `tests/test_session_marking.py` enforces.
    """
    async with worker_session_factory()() as session:
        row = await session.execute(
            select(TenantModel.id).where(TenantModel.id == tenant_id)
        )
        return row.scalar_one_or_none() is not None


async def _run_one_job(
    *,
    tenant_id: uuid.UUID,
    trigger: PropertyStateTrigger,
    task_name: str,
    now: datetime,
) -> AdvanceReport | tuple[str, str]:
    """One clock job, in its own marked session (R1, D5).

    The use case commits its own transaction through its `SqlAlchemyUnitOfWork`,
    so this wrapper only opens/closes the session and marks it. Returns the
    `AdvanceReport` on success, or `(cls_name, msg)` on failure — the traceback
    is sent to the log (R1.6, `logger.exception`) and the caller prints the
    operator-facing single-line summary required by D4.
    """
    async with worker_session_factory()() as session:
        bind_session_to_tenant(session, tenant_id)
        try:
            return await _advance(
                session, tenant_id, now, trigger=trigger
            )
        except Exception as exc:
            await session.rollback()
            logger.exception(
                "sim_advance.job_failed",
                extra={"task": task_name, "tenant_id": str(tenant_id)},
            )
            return (type(exc).__name__, str(exc))


def _format_report_line(tenant_id: uuid.UUID, report: AdvanceReport) -> str:
    """One line per job (D4, R1).

    The required buckets, in the order the task specifies, plus `not_eligible`
    (the dataclass always carries it — "when emitted" is the use case's contract,
    not a runtime check).
    """
    return (
        f"sim-advance: tenant={tenant_id} "
        f"trigger={report.trigger} "
        f"candidates={report.candidates} "
        f"transitioned={report.transitioned} "
        f"blocked={report.blocked} "
        f"ambiguous={report.ambiguous} "
        f"unresolvable_time={report.unresolvable_time} "
        f"transitioned_without_task={report.transitioned_without_task} "
        f"not_eligible={report.not_eligible}"
    )


def _env_guard() -> int | None:
    """Return the exit code if the environment guard fails, else `None`.

    D5: refuse anything outside `{"local", "dev"}` BEFORE any DB session is opened
    (rule 8 of `steering/security.md`).
    """
    if settings.environment in _ALLOWED_ENVIRONMENTS:
        return None
    allowed = sorted(_ALLOWED_ENVIRONMENTS)
    print(
        f"sim_advance: refusing to run — environment={settings.environment!r}; "
        f"accepted values are {allowed}",
        file=sys.stderr,
    )
    return 1


async def _run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    tenant_id: uuid.UUID = args.tenant
    # R1: resolve `now` ONCE at the top, pass by value to every job. No re-read of
    # `datetime.now(UTC)` between jobs, even when `--at` is absent.
    now: datetime = args.at if args.at is not None else datetime.now(UTC)

    # R1: the first line of output is the resolved now, regardless of what follows.
    # R1.3: the suffix names whether the real clock or `--at` produced it, so an operator
    # skimming a log can tell the two cases apart without checking argv.
    now_source = "--at" if args.at is not None else "live clock"
    print(f"sim-advance: now = {now.isoformat()} ({now_source})")

    guard = _env_guard()
    if guard is not None:
        return guard

    if not await _tenant_exists(tenant_id):
        print(
            f"sim_advance: refusing to run — tenant {tenant_id} does not exist",
            file=sys.stderr,
        )
        return 1

    succeeded = 0
    failed = 0
    for task_name, trigger in _CLOCK_JOBS:
        result = await _run_one_job(
            tenant_id=tenant_id,
            trigger=trigger,
            task_name=task_name,
            now=now,
        )
        if isinstance(result, tuple):
            cls_name, msg = result
            # D4 + R1.6: single-line summary on stderr so the operator sees
            # the failure without grepping the log; traceback itself is the
            # `logger.exception` call inside `_run_one_job`.
            print(
                f"sim-advance: {trigger.value} FAILED: {cls_name}: {msg}",
                file=sys.stderr,
            )
            failed += 1
            continue
        succeeded += 1
        print(_format_report_line(tenant_id, result))

    # D4: 0 all OK, 1 ALL failed, 2 some but not all failed.
    if failed == 0:
        return 0
    if succeeded == 0:
        return 1
    return 2


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())