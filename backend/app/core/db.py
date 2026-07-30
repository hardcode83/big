import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid, event, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    ORMExecuteState,
    Session,
    declared_attr,
    mapped_column,
    with_loader_criteria,
)

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantScopedMixin:
    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)


TENANT_ID_SESSION_KEY = "tenant_id"


def tenant_scoped_classes() -> list[type]:
    """Every mapped class carrying a `tenant_id` column.

    Resolved from the mapper registry rather than from `issubclass(...,
    TenantScopedMixin)`: an unmapped mixin is not an entity, so it cannot be handed
    to `with_loader_criteria`.

    Deliberately NOT memoised. `Base.registry.mappers` only grows as model modules
    get imported, so a cached result would permanently exclude any entity whose
    module was imported after the first filtered query — a lazy import inside a
    function, or a worker entrypoint with a different import graph. Silently
    excluding `guests`, which holds the `document_number` PII, is not a trade worth
    making to skip a scan over a couple of dozen mappers.
    """
    return [mapper.class_ for mapper in Base.registry.mappers if "tenant_id" in mapper.columns]


@event.listens_for(Session, "do_orm_execute")
def _scope_statement_to_tenant(execute_state: ORMExecuteState) -> None:
    """Defence in depth for tenant isolation (R4.2, design D16).

    Only active on sessions marked with a tenant — `get_authenticated_request`
    does that after verifying the token. The authoritative mechanism is still the
    explicit `tenant_id` parameter every repository method takes (design D6); this
    is the net that stops a forgotten filter from becoming a leak.

    Five limits, deliberately not disguised:

    1. It covers ORM SELECT/UPDATE/DELETE only. A `session.execute(text(...))` or a
       hand-built Core statement bypasses it entirely.
    2. It does nothing on a session without a tenant marker. Unmarked: Celery tasks,
       the bootstrap command, the anonymous login query — which *needs* it, because
       `find_by_email_across_tenants` has no tenant yet — and `POST /auth/refresh`,
       which is anonymous and so never reaches `get_authenticated_request`, the only
       place that marks. Any future anonymous endpoint touching data inherits this.
    3. INSERTs are not guarded. `session.add` emits no ORM statement this listener
       can rewrite, so a cross-tenant insert is stopped only by the explicit check
       in the repository (`add()` refuses a foreign `tenant_id`).
    4. The identity map is not covered. `session.get()`/`session.refresh()` can
       return an object already loaded without emitting SQL, so a row read while the
       session was unmarked stays reachable afterwards. That is why entities loaded
       on the anonymous login path must not be handed to a marked session.

    5. Child tables with no `tenant_id` of their own are out of reach (`messages`,
       `cleaning_checklist_completions`, `cleaning_photos`): they hang off a scoped
       parent, and this scan matches on column presence. Any repository touching them
       must join the scoped parent explicitly and bring its own isolation test.

    Rows 3, 4 and 5 are why the explicit `tenant_id` of design D6 remains the
    authoritative mechanism and this is only the net.
    """
    tenant_id = execute_state.session.info.get(TENANT_ID_SESSION_KEY)
    if tenant_id is None:
        return
    if execute_state.is_column_load or execute_state.is_relationship_load:
        # Refreshing a deferred column or loading a relationship reuses the parent
        # statement's criteria; re-adding options here would double them.
        return
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return

    for entity in tenant_scoped_classes():
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(entity, entity.tenant_id == tenant_id, include_aliases=True)
        )


def bind_session_to_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    session.info[TENANT_ID_SESSION_KEY] = tenant_id


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """One session per request, always closed (R6.3, design D10).

    The transactional boundary is the use case: it calls `commit()` when the
    business operation completes. This dependency only guarantees that a request
    ending in an exception leaves nothing half-written, and that the connection
    goes back to the pool either way.
    """
    session = async_session_factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
