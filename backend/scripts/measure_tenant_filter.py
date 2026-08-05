"""Measure what the global tenant filter costs in the one-minute job (`celery-jobs` R6).

`_scope_statement_to_tenant` (`app/core/db.py`) attaches a `with_loader_criteria` per scoped
class **per ORM statement**, and it is deliberately not memoised — `tenant_scoped_classes()`
resolves from the mapper registry every time, because caching it would permanently exclude
any entity whose module is imported later.

`check_sla_breaches` runs every minute, which makes it the highest-frequency consumer in the
project and therefore the honest place to put a number on that. What matters is the product
*cost per statement × statements per run*, so this counts rather than profiles:

* how many ORM statements the listener actually intercepts in one run,
* how many classes `tenant_scoped_classes()` returns during it — recorded so a future
  measurement is comparable when that number has grown,
* the wall time spent inside the listener, and the run's total.

Run it against the dev stack:

    docker compose exec backend uv run python -m scripts.measure_tenant_filter

**It seeds real rows and deletes them again — it does not roll them back**, and the difference
matters. An earlier version claimed a rollback cleaned everything up; it did not, because
`EscalateBreachedSlasUseCase.execute` commits internally, so by the time this script reached
its own `rollback()` there was nothing left to undo. Three runs of it left three permanent
`ACTIVE` tenants in the dev database, which the scheduler then processed on every tick
forever. Found by the feature-scale review panel, which counted the residue.

The cleanup is now explicit — and it runs on the **success path only**, at the end of the
`try`, not in a `finally`. That is a deliberate limit and not an oversight: between the use
case's internal commit and the delete a few statements later, the rows are durable, so a
`Ctrl-C` or a database error in that window still leaves them behind. A `finally` would
narrow the window, not close it, and it would run against a session that may already be in a
failed transaction. Point `DATABASE_URL` at a development database, and if a run is
interrupted, delete the `measure-*` tenant by hand.
"""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import app.core.models_registry  # noqa: F401
from sqlalchemy import delete, event
from sqlalchemy.orm import ORMExecuteState, Session

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.core import db as core_db
from app.core.db import async_session_factory, bind_session_to_tenant, tenant_scoped_classes
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.application.use_cases import EscalateBreachedSlasUseCase
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.notifications.infrastructure.models import NotificationLogModel
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.tenants.infrastructure.models import TenantModel

BREACHES = 50
MANAGERS = 3


class Probe:
    """Counts interceptions and the time spent inside the listener."""

    def __init__(self) -> None:
        self.statements = 0
        self.seconds = 0.0
        self.classes_seen = 0

    def wrap(self):
        original = core_db._scope_statement_to_tenant

        def measured(execute_state: ORMExecuteState) -> None:
            started = time.perf_counter()
            original(execute_state)
            elapsed = time.perf_counter() - started
            if execute_state.session.info.get(core_db.TENANT_ID_SESSION_KEY) is not None:
                self.statements += 1
                self.seconds += elapsed
            self.classes_seen = max(self.classes_seen, len(tenant_scoped_classes()))

        event.remove(Session, "do_orm_execute", original)
        event.listen(Session, "do_orm_execute", measured)
        return original, measured


async def _delete_seeded(session, tenant_id) -> None:
    """Remove everything this run created, children first.

    A plain `rollback()` cannot do this: the use case under measurement commits, which is
    part of what makes the measurement realistic. Deleting is the honest alternative.
    """
    await session.execute(
        delete(NotificationLogModel).where(NotificationLogModel.tenant_id == tenant_id)
    )
    await session.execute(delete(UserModel).where(UserModel.tenant_id == tenant_id))
    await session.execute(delete(TenantModel).where(TenantModel.id == tenant_id))
    await session.commit()


async def main() -> None:
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    probe = Probe()
    original, measured = probe.wrap()
    try:
        async with async_session_factory() as session:
            tenant = TenantModel(
                name=f"measure-{uuid.uuid4().hex[:8]}",
                billing_email=f"measure-{uuid.uuid4().hex[:8]}@example.com",
            )
            session.add(tenant)
            await session.flush()
            for index in range(MANAGERS):
                session.add(
                    UserModel(
                        tenant_id=tenant.id,
                        name=f"Mgr{index}",
                        email=f"mgr{index}-{uuid.uuid4().hex[:8]}@example.com",
                        password_hash="x",
                        role=UserRole.PROPERTY_MANAGER,
                        status=UserStatus.ACTIVE,
                    )
                )
            for index in range(BREACHES):
                session.add(
                    NotificationLogModel(
                        tenant_id=tenant.id,
                        recipient_contact="cleaner@example.com",
                        channel=NotificationChannel.EMAIL,
                        notification_type=NotificationType.CLEANING_TASK_ASSIGNED.value,
                        status=NotificationStatus.SENT,
                        sla_deadline_at=now - timedelta(minutes=index + 1),
                    )
                )
            await session.flush()

            # Marked exactly as the scheduler's runner marks it, which is what switches the
            # listener on for this session.
            bind_session_to_tenant(session, tenant.id)
            use_case = EscalateBreachedSlasUseCase(
                notifications=SqlAlchemyNotificationLogRepository(session),
                users=SqlAlchemyUserRepository(session),
                uow=SqlAlchemyUnitOfWork(session),
            )
            started = time.perf_counter()
            report = await use_case.execute(tenant_id=tenant.id, now=now)
            total = time.perf_counter() - started
            await _delete_seeded(session, tenant.id)
    finally:
        event.remove(Session, "do_orm_execute", measured)
        event.listen(Session, "do_orm_execute", original)

    per_statement_us = (probe.seconds / probe.statements * 1e6) if probe.statements else 0.0
    print(f"breaches seeded          : {BREACHES}")
    print(f"escalations written      : {report.rows_written}")
    print(f"scoped classes           : {probe.classes_seen}")
    print(f"ORM statements filtered  : {probe.statements}")
    print(f"time inside the listener : {probe.seconds * 1000:.2f} ms")
    print(f"  per statement          : {per_statement_us:.1f} us")
    print(f"total run time           : {total * 1000:.2f} ms")
    if total:
        print(f"listener share of the run: {probe.seconds / total * 100:.1f} %")


if __name__ == "__main__":
    asyncio.run(main())
