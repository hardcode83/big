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
from app.core.tenancy import TenantMarkedSessionError


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
       `find_by_email_globally` has no tenant yet — and `POST /auth/refresh`,
       which is anonymous and so never reaches `get_authenticated_request`. That
       dependency is the usual marker but **not the only one**, so being anonymous is no
       guarantee of being unmarked: what decides it is where the request is in its
       sequence, not which kind of route it is. Any future anonymous endpoint touching
       data inherits this limit.

       **Which things mark a session is deliberately not enumerated here.** That list went
       stale every time one was added, and the reads that care do not need it: they call
       `require_unmarked_session` below, which refuses a marked session outright instead of
       letting this listener scope the statement in silence. That guard is where the
       invariant lives now, and `tests/test_unscoped_reads.py` is what keeps the set of
       reads subject to it honest.

       **`app/cli/seed_demo.py` reads unmarked and then marks the same session mid-run**,
       and it belongs in this list precisely because it does not fit it. It is not the
       first to do that — `GuestPortalAuthenticator` (`app/guests/application/portal.py`)
       resolves a token on an unmarked session and binds afterwards — so what earns the
       entry is the shape, not being first. It reads two things while unmarked, and they
       are not the same kind of read:

       * the **tenant**, resolved by NAME — `TenantModel` carries no `tenant_id`, so it is
         not one of the scoped classes below and this listener would never have filtered
         it. Two plain values come off that row: its `id`, which is the argument to the bind
         and then flows into every write of the run, and its `timezone`, which anchors the
         demo dataset's dates to the tenant's own calendar day. Both are scalars read before
         the bind rather than an entity carried across it, which is why neither is what the
         constraint below is about;
       * `find_by_email_globally`, which returns a **`User`** — a scoped class. This one
         must precede the bind or the listener scopes it and the cross-tenant conflict
         check silently stops being global.

       The constraint is therefore about the second read only, and it is limit 4 below: a
       scoped row loaded while unmarked stays reachable afterwards. So the entity that
       lookup returns is only ever asked two questions — which tenant owns it, for the
       refusal, and whether it exists at all, for the "leave it alone" skip — and is never
       mutated, never carried into a write, never re-attached. Copy the sequence only with
       that attached.

       This is how `webhook_events` rows whose `tenant_id` is NULL are reached through
       the ORM. That column is nullable by design (§7.26: a payload that cannot be
       attributed is recorded rather than lost), but the scan below matches on column
       presence, so a marked session filters `tenant_id = X` and those rows come back
       empty with no error.

       **`reservations-webhooks` must use a session that was NEVER marked** — its own,
       straight from `async_session_factory`, the way `app/cli/bootstrap.py` and
       `app/integrations/cli/pms_sync.py` already do. It must NOT pop the marker off a
       session that has one: `session.info` is per-session, not per-statement, so
       un-marking mid-request disables this net for **every** scoped table for the rest
       of that session — `guests.document_number` included. There is no supported way
       to exempt one table for one query; if you find yourself wanting that, the read
       belongs in a different session. Pinned by
       `tests/test_tenant_filter.py::test_webhook_events_without_a_tenant_are_invisible_to_a_marked_session`.
    3. INSERTs are not guarded. `session.add` emits no ORM statement this listener
       can rewrite, so a cross-tenant insert is stopped only by the explicit check
       in the repository (`add()` refuses a foreign `tenant_id`).
    4. The identity map is not covered. `session.get()`/`session.refresh()` can
       return an object already loaded without emitting SQL, so a row read while the
       session was unmarked stays reachable afterwards. That is why entities loaded
       on the anonymous login path must not be handed to a marked session.

    5. Child tables with no `tenant_id` of their own are out of reach (`messages`,
       `cleaning_checklist_completions`, `cleaning_photos`, `review_response_drafts`):
       they hang off a scoped parent, and this scan matches on column presence. Any
       repository touching them must join the scoped parent explicitly and bring its
       own isolation test.

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
    """Mark a session with its tenant. One-way: there is no unbind, by design.

    The two guards below amend `auth-tenancy`'s design D16, which shipped this as a
    bare assignment. They exist because the setter turned out to be its own unbind:
    `bind_session_to_tenant(session, None)` writes NULL, `_scope_statement_to_tenant`
    returns early on NULL, and the net is off for every scoped table for the rest of
    that session — `guests.document_number` included. Re-marking is worse than that:
    it repoints the filter at a foreign tenant instead of just removing it.

    The `uuid.UUID` annotation protected nothing: this backend runs no mypy and no
    ruff (`pyproject.toml` declares only pytest), and CI runs neither.

    Added by `domain-foundation-financial` because that change made the hole easier to
    reach, not harder: `webhook_events` is the first table whose legitimate read path
    needs the filter off, and `tests/test_session_marking.py` bans the `session.info`
    route — which leaves this function as the obvious thing to reach for. Read
    unmarked data from a session that was NEVER marked instead.
    """
    if tenant_id is None:
        raise ValueError(
            "a session cannot be bound to a null tenant: that silently disables the "
            "global filter for every scoped table. Use a session that was never marked."
        )
    current = session.info.get(TENANT_ID_SESSION_KEY)
    if current is not None and current != tenant_id:
        raise ValueError(
            f"session is already bound to tenant {current}; rebinding it to {tenant_id} "
            "would repoint the global filter at another tenant mid-session"
        )
    session.info[TENANT_ID_SESSION_KEY] = tenant_id


def require_unmarked_session(session: AsyncSession, *, read: str) -> None:
    """Refuse an unscoped read on a session that already carries a tenant marker.

    This is where the invariant of limit 2 lives now. It used to live in prose, restated across
    several files, and **every version of that count was wrong at some point** — including the
    ones written by the change that removed it, twice, during its own review. No number is
    repeated here for that reason: a `raise` cannot go
    stale, and the set of callers of this function is the audited census of the reads that
    resolve a tenant out of the row they read (`tests/test_unscoped_reads.py` pins it).

    That census is not the set of every query in the system that runs without a tenant, and
    the difference is written down rather than left to be discovered: `select_pending` and
    `lease` (`app/integrations/infrastructure/repositories.py`) also require an unmarked session
    and do not call this guard. They are a **different class** — they drain a queue that
    deliberately holds `tenant_id IS NULL` rows, and a marked session hides those without
    erroring, so what protects them is not this question. `test_tenant_filter.py` pins them.

    `tests/test_unscoped_reads.py` holds both the census and that boundary. Worth knowing why it
    holds the second: `find_by_token_hash` sat outside the census for two changes while three
    prose sites claimed the census was the whole class. Declaring the boundary is what turned
    that from an invisible gap into a one-line fix.

    It lives here and not in the adapters that hold those reads because
    `tests/test_session_marking.py` bans every access to `session.info` in `app/` outside this
    module — that ban is the guard that keeps anyone from switching the global filter off
    mid-request, and relaxing it to let those adapters peek would cost more than it buys.

    `read` names the caller in the message, because the failure a reader has to diagnose is
    "which read ran too late", not "a session was marked".
    """
    tenant_id = session.info.get(TENANT_ID_SESSION_KEY)
    if tenant_id is not None:
        raise TenantMarkedSessionError(read=read, tenant_id=tenant_id)


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
