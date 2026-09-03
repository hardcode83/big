"""`SqlAlchemyPropertyRepository` — resolution and tenant scoping (R1.4, R3.4, R4, R5.1).

The cross-tenant cases are not an extra: they are what makes `404` (design D6) reachable
instead of a leak, so each lookup has a neighbour it must fail to find.

`list_by_state`, `save` and `SqlAlchemyPropertyStateTransitionRepository` arrive with
`celery-jobs` (its R2, R3), which is the first writer of operational state.
"""

import inspect
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.core.tenancy import CrossTenantWriteError
from app.integrations.domain.enums import PMSProvider
from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import (
    PropertyOperationalState,
    PropertyStatus,
    StateTransitionTriggeredBy,
)
from app.properties.domain.exceptions import AmbiguousPropertyExternalIdError
from app.properties.domain.repositories import PropertyStateTransitionRepository

from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.tenants.infrastructure.models import TenantModel
from tests.sql_counter import count_statements


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _property(
    db_session,
    tenant: TenantModel,
    *,
    internal_code: str,
    pms_external_id: str | None = None,
    state: PropertyOperationalState = PropertyOperationalState.VACANT_READY,
    pms_provider: PMSProvider | None = None,
    status: PropertyStatus = PropertyStatus.ACTIVE,
) -> PropertyModel:
    model = PropertyModel(
        tenant_id=tenant.id,
        name=internal_code,
        internal_code=internal_code,
        pms_external_id=pms_external_id,
        pms_provider=pms_provider,
        status=status,
        current_operational_state=state,
    )
    db_session.add(model)
    await db_session.flush()
    return model


@pytest.mark.asyncio
async def test_get_finds_the_property_of_its_tenant(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")

    found = await SqlAlchemyPropertyRepository(db_session).get(tenant.id, model.id)

    assert found is not None
    assert found.id == model.id
    assert found.internal_code == "REDES11"


@pytest.mark.asyncio
async def test_get_does_not_reach_another_tenants_property(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, internal_code="PAJARITOS8")

    found = await SqlAlchemyPropertyRepository(db_session).get(tenant_a.id, theirs.id)

    assert found is None


@pytest.mark.asyncio
async def test_get_of_an_unknown_id_is_none_not_an_error(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")

    found = await SqlAlchemyPropertyRepository(db_session).get(tenant.id, uuid.uuid4())

    assert found is None


@pytest.mark.asyncio
async def test_find_by_internal_code_within_the_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _property(db_session, tenant_a, internal_code="REDES11")
    # Same code in the neighbour tenant: allowed by the schema (the constraint is
    # per tenant), and exactly the case a missing filter would confuse.
    await _property(db_session, tenant_b, internal_code="REDES11")

    repository = SqlAlchemyPropertyRepository(db_session)

    assert (await repository.find_by_internal_code(tenant_a.id, "REDES11")).id == mine.id
    assert await repository.find_by_internal_code(tenant_a.id, "UNKNOWN") is None


@pytest.mark.asyncio
async def test_find_by_internal_code_ignores_surrounding_whitespace(db_session) -> None:
    """A CSV cell arrives with whatever the spreadsheet left in it (R4)."""
    tenant = await _tenant(db_session, "TenantA")
    mine = await _property(db_session, tenant, internal_code="REDES11")

    found = await SqlAlchemyPropertyRepository(db_session).find_by_internal_code(
        tenant.id, "  REDES11 "
    )

    assert found is not None
    assert found.id == mine.id


@pytest.mark.asyncio
async def test_find_by_pms_external_id_within_the_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _property(db_session, tenant_a, internal_code="REDES11", pms_external_id="PMS-1")
    await _property(db_session, tenant_b, internal_code="OTHER", pms_external_id="PMS-1")

    repository = SqlAlchemyPropertyRepository(db_session)

    assert (await repository.find_by_pms_external_id(tenant_a.id, "PMS-1")).id == mine.id
    assert await repository.find_by_pms_external_id(tenant_a.id, "PMS-9") is None


@pytest.mark.asyncio
async def test_an_ambiguous_pms_external_id_fails_closed(db_session) -> None:
    """Two properties, one external id: refuse rather than attach a guest to a coin flip.

    It refuses with a DOMAIN error, so the PMS sync can report the row without catching a
    SQLAlchemy exception inside `application/` (design D16).

    **The two properties are on different providers, and that is load-bearing.**
    `properties-crud` (design D5) added the partial unique index
    `uq_properties_tenant_id_pms_external_id`, keyed on `coalesce(pms_provider, 'MOCK')` — so
    within one provider this ambiguity can no longer be created, which is the point: the new
    write path could otherwise produce it one request at a time. Across providers it stays legal,
    because external ids are unique only WITHIN a provider and a tenant mid-migration
    legitimately has the same id on two of them (ADR 0006 decision 7).

    That is exactly why this guard is still reachable rather than dead: `find_by_pms_external_id`
    looks up tenant-wide, without a provider, so a legitimate cross-provider pair returns two rows
    and it must refuse instead of picking one.
    """
    tenant = await _tenant(db_session, "TenantA")
    await _property(
        db_session,
        tenant,
        internal_code="REDES11",
        pms_external_id="PMS-DUP",
        pms_provider=PMSProvider.BEDS24,
    )
    await _property(
        db_session,
        tenant,
        internal_code="PAJARITOS8",
        pms_external_id="PMS-DUP",
        pms_provider=PMSProvider.CHANNEX,
    )

    with pytest.raises(AmbiguousPropertyExternalIdError):
        await SqlAlchemyPropertyRepository(db_session).find_by_pms_external_id(
            tenant.id, "PMS-DUP"
        )


@pytest.mark.asyncio
async def test_list_by_state_returns_only_the_requested_states(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    vacant = await _property(
        db_session, tenant, internal_code="REDES11", state=PropertyOperationalState.VACANT_READY
    )
    awaiting = await _property(
        db_session,
        tenant,
        internal_code="PAJARITOS8",
        state=PropertyOperationalState.AWAITING_CHECKIN,
    )
    await _property(
        db_session,
        tenant,
        internal_code="OCCUPIED1",
        state=PropertyOperationalState.OCCUPIED_ESTIMATED,
    )

    found = await SqlAlchemyPropertyRepository(db_session).list_by_state(
        tenant.id,
        [PropertyOperationalState.VACANT_READY, PropertyOperationalState.AWAITING_CHECKIN],
    )

    assert {p.id for p in found} == {vacant.id, awaiting.id}


@pytest.mark.asyncio
async def test_list_by_state_does_not_reach_another_tenant(db_session) -> None:
    """The isolation test rule 1 of `steering/security.md` requires for this query.

    A scheduled job iterates tenants in one process, so a missing filter here would not
    leak a read — it would transition a neighbour's flat.
    """
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _property(db_session, tenant_a, internal_code="REDES11")
    await _property(db_session, tenant_b, internal_code="THEIRS")

    found = await SqlAlchemyPropertyRepository(db_session).list_by_state(
        tenant_a.id, [PropertyOperationalState.VACANT_READY]
    )

    assert [p.id for p in found] == [mine.id]


@pytest.mark.asyncio
async def test_list_by_state_without_states_returns_empty_without_querying(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    await _property(db_session, tenant, internal_code="REDES11")

    assert await SqlAlchemyPropertyRepository(db_session).list_by_state(tenant.id, []) == []


# --- `states_for` (`cleaning-assign-preconditions` R3.2, design D6) -------------------


@pytest.mark.asyncio
async def test_states_for_maps_every_requested_id_to_its_state(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    awaiting = await _property(
        db_session,
        tenant,
        internal_code="REDES11",
        state=PropertyOperationalState.AWAITING_CLEANING,
    )
    occupied = await _property(
        db_session,
        tenant,
        internal_code="PAJARITOS8",
        state=PropertyOperationalState.OCCUPIED_ESTIMATED,
    )
    unasked = await _property(db_session, tenant, internal_code="UNASKED1")

    states = await SqlAlchemyPropertyRepository(db_session).states_for(
        tenant.id, [awaiting.id, occupied.id]
    )

    assert states == {
        awaiting.id: PropertyOperationalState.AWAITING_CLEANING,
        occupied.id: PropertyOperationalState.OCCUPIED_ESTIMATED,
    }
    assert unasked.id not in states


@pytest.mark.asyncio
async def test_states_for_omits_an_id_that_does_not_exist(db_session) -> None:
    """A missing key means "unknown", which is what lets `cleaning` fail open (R3.3).

    If this returned a default instead, the screen would be told a flat is in some state
    nobody ever wrote — and the fail-open of design D4 would never be reachable.
    """
    tenant = await _tenant(db_session, "TenantA")
    known = await _property(db_session, tenant, internal_code="REDES11")
    ghost = uuid.uuid4()

    states = await SqlAlchemyPropertyRepository(db_session).states_for(
        tenant.id, [known.id, ghost]
    )

    assert set(states) == {known.id}


@pytest.mark.asyncio
async def test_states_for_without_ids_returns_empty_without_querying(
    db_session, monkeypatch
) -> None:
    """"Without querying" is asserted here, not just claimed in the name.

    The port promises it, mirroring what `list_by_state` promises for an empty `states`, and a
    page of cleaning tasks with no rows is the ordinary case that reaches it. So the session's
    `execute` is wrapped to record calls: an implementation that dropped the early return would
    still return `{}` and would pass a weaker test.
    """
    tenant = await _tenant(db_session, "TenantA")
    await _property(db_session, tenant, internal_code="REDES11")
    calls: list[object] = []
    original = db_session.execute

    async def recording_execute(*args, **kwargs):
        calls.append(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(db_session, "execute", recording_execute)

    assert await SqlAlchemyPropertyRepository(db_session).states_for(tenant.id, []) == {}
    assert calls == []


@pytest.mark.asyncio
async def test_states_for_does_not_reach_another_tenant(db_session) -> None:
    """Rule 1 of `steering/security.md`, and DoD §28.18, for this query.

    The ids arrive from a page of cleaning tasks, which is already tenant-scoped — so the
    realistic failure is not an attacker guessing a uuid but a future caller passing ids from
    somewhere else. Asking for a neighbour's id must be indistinguishable from asking for one
    that does not exist: absent from the mapping, no error, nothing that confirms it is there.
    """
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _property(
        db_session,
        tenant_a,
        internal_code="REDES11",
        state=PropertyOperationalState.AWAITING_CLEANING,
    )
    theirs = await _property(
        db_session,
        tenant_b,
        internal_code="THEIRS",
        state=PropertyOperationalState.OCCUPIED_ESTIMATED,
    )

    states = await SqlAlchemyPropertyRepository(db_session).states_for(
        tenant_a.id, [mine.id, theirs.id]
    )

    assert states == {mine.id: PropertyOperationalState.AWAITING_CLEANING}


# --- `list_by_status` (`revenue-pricing` R4.1, design D17) ----------------------------


@pytest.mark.asyncio
async def test_list_by_status_returns_only_that_status(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    live = await _property(db_session, tenant, internal_code="REDES11")
    await _property(
        db_session, tenant, internal_code="RETIRED1", status=PropertyStatus.INACTIVE
    )

    found = await SqlAlchemyPropertyRepository(db_session).list_by_status(
        tenant.id, PropertyStatus.ACTIVE
    )

    assert [p.id for p in found] == [live.id]


@pytest.mark.asyncio
async def test_list_by_status_does_not_reach_another_tenant(db_session) -> None:
    """Rule 1 of `steering/security.md`, and it bites for the same reason `list_by_state`
    does: the nightly pricing job iterates tenants in one process, so a missing filter
    would price a neighbour's flat."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _property(db_session, tenant_a, internal_code="REDES11")
    await _property(db_session, tenant_b, internal_code="THEIRS")

    found = await SqlAlchemyPropertyRepository(db_session).list_by_status(
        tenant_a.id, PropertyStatus.ACTIVE
    )

    assert [p.id for p in found] == [mine.id]


@pytest.mark.asyncio
async def test_list_by_status_is_ordered_deterministically(db_session) -> None:
    """A failing nightly run has to be reproducible, not order-dependent."""
    tenant = await _tenant(db_session, "TenantA")
    for code in ("ZULU", "ALFA", "MIKE"):
        await _property(db_session, tenant, internal_code=code)

    found = await SqlAlchemyPropertyRepository(db_session).list_by_status(
        tenant.id, PropertyStatus.ACTIVE
    )

    assert [p.internal_code for p in found] == ["ALFA", "MIKE", "ZULU"]


@pytest.mark.asyncio
async def test_list_by_status_is_not_list_by_state(db_session) -> None:
    """D17: a property being cleaned still has a calendar and still needs a price."""
    tenant = await _tenant(db_session, "TenantA")
    occupied = await _property(
        db_session,
        tenant,
        internal_code="REDES11",
        state=PropertyOperationalState.OCCUPIED_ESTIMATED,
    )

    found = await SqlAlchemyPropertyRepository(db_session).list_by_status(
        tenant.id, PropertyStatus.ACTIVE
    )

    assert [p.id for p in found] == [occupied.id]


@pytest.mark.asyncio
async def test_save_persists_the_operational_state(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    repository = SqlAlchemyPropertyRepository(db_session)

    entity = await repository.get(tenant.id, model.id)
    entity.current_operational_state = PropertyOperationalState.AWAITING_CHECKIN
    await repository.save(tenant.id, entity)

    reloaded = await repository.get(tenant.id, model.id)
    assert reloaded.current_operational_state is PropertyOperationalState.AWAITING_CHECKIN


@pytest.mark.asyncio
async def test_save_leaves_every_other_column_alone(db_session) -> None:
    """`save` is deliberately narrow (design D6): only the operational state travels."""
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    repository = SqlAlchemyPropertyRepository(db_session)

    entity = await repository.get(tenant.id, model.id)
    entity.current_operational_state = PropertyOperationalState.AWAITING_CHECKIN
    entity.name = "renamed in memory"
    entity.max_guests = 99
    await repository.save(tenant.id, entity)

    reloaded = await repository.get(tenant.id, model.id)
    assert reloaded.name == "REDES11"
    assert reloaded.max_guests == 2


@pytest.mark.asyncio
async def test_save_refuses_a_property_of_another_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, internal_code="THEIRS")

    entity = await SqlAlchemyPropertyRepository(db_session).get(tenant_b.id, theirs.id)

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyPropertyRepository(db_session).save(tenant_a.id, entity)


@pytest.mark.asyncio
async def test_list_all_does_not_reach_another_tenant(db_session) -> None:
    """Rule 1 of `steering/security.md`, proved on the query and not on the net.

    `list_all` had no test of its own here, and `cleaning-stall-blocks-next-stay` gave it a
    portfolio-wide HTTP consumer (`GET /api/v1/blocked-transitions`). Its API-level isolation
    tests cannot cover this: they share one session that `bind_session_to_tenant` has marked, and
    `app/core/db.py`'s `with_loader_criteria` net would return the same empty result even with the
    explicit `WHERE tenant_id` deleted. This session is never bound, so what passes here is the
    predicate — which is what `app/core/db.py` itself calls "the authoritative mechanism", the net
    being only a net. Its two other callers are jobs that use it on unmarked sessions.
    """
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    await _property(db_session, tenant_b, internal_code="THEIRS")
    mine = await _property(db_session, tenant_a, internal_code="MINE")

    found = await SqlAlchemyPropertyRepository(db_session).list_all(tenant_a.id)

    assert [prop.id for prop in found] == [mine.id]


def _transition(tenant_id, property_id, **overrides) -> PropertyStateTransition:
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        property_id=property_id,
        from_state=PropertyOperationalState.VACANT_READY,
        to_state=PropertyOperationalState.AWAITING_CHECKIN,
        triggered_by=StateTransitionTriggeredBy.SYSTEM,
        created_at=datetime(2026, 8, 4, 10, 0, tzinfo=UTC),
        reason="check-in window opened",
        metadata={"trigger": "CHECKIN_WINDOW_OPENED"},
    )
    return PropertyStateTransition(**{**defaults, **overrides})


@pytest.mark.asyncio
async def test_transition_add_persists_every_field(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    transition = _transition(tenant.id, model.id)

    await SqlAlchemyPropertyStateTransitionRepository(db_session).add(tenant.id, transition)

    stored = (
        await db_session.execute(
            select(PropertyStateTransitionModel).where(
                PropertyStateTransitionModel.id == transition.id
            )
        )
    ).scalar_one()
    assert stored.from_state is PropertyOperationalState.VACANT_READY
    assert stored.to_state is PropertyOperationalState.AWAITING_CHECKIN
    assert stored.triggered_by is StateTransitionTriggeredBy.SYSTEM
    assert stored.triggered_by_user_id is None
    assert stored.reason == "check-in window opened"
    # The column is `metadata` in Postgres, reached through `metadata_` in the model.
    assert stored.metadata_ == {"trigger": "CHECKIN_WINDOW_OPENED"}
    assert stored.created_at == datetime(2026, 8, 4, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_transition_add_refuses_another_tenants_transition(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, internal_code="THEIRS")

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyPropertyStateTransitionRepository(db_session).add(
            tenant_a.id, _transition(tenant_b.id, theirs.id)
        )


# --- `applied_clock_triggers` (`cleaning-stall-blocks-next-stay` R1.1, design D1) -------
#
# Against the real database on purpose. The in-memory fake reads the two keys off a Python dict
# while this reads them out of JSONB with `->>`, and a fake that agreed with the test while
# disagreeing with Postgres is the exact failure the `fixtures-and-real-writers-disagree` note
# records: a green suite over a production bug.


@pytest.mark.asyncio
async def test_applied_clock_triggers_reads_the_pair_out_of_jsonb(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    reservation_id = uuid.uuid4()
    await SqlAlchemyPropertyStateTransitionRepository(db_session).add(
        tenant.id,
        _transition(
            tenant.id,
            model.id,
            metadata={
                "trigger": "CHECKIN_TIME_REACHED",
                "reservation_id": str(reservation_id),
            },
        ),
    )

    found = await SqlAlchemyPropertyStateTransitionRepository(db_session).applied_clock_triggers(
        tenant.id, [reservation_id]
    )

    assert found == {(reservation_id, "CHECKIN_TIME_REACHED")}


@pytest.mark.asyncio
async def test_applied_clock_triggers_is_empty_without_ids_and_does_not_query(
    db_session, monkeypatch
) -> None:
    """The early return is asserted, not just its result.

    Without the `execute` spy this test passed on the empty return value alone, so removing the
    guard and emitting an `IN ()` would have kept it green — the name would have been the only
    thing claiming a query was avoided.
    """
    tenant = await _tenant(db_session, "TenantA")
    executed: list[object] = []
    original = db_session.execute

    async def spy(statement, *args, **kwargs):
        executed.append(statement)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", spy)

    found = await SqlAlchemyPropertyStateTransitionRepository(db_session).applied_clock_triggers(
        tenant.id, []
    )

    assert found == set()
    assert executed == []


@pytest.mark.asyncio
async def test_applied_clock_triggers_skips_rows_without_a_reservation(db_session) -> None:
    """A manual transition carries no `reservation_id`, and must not become a `(None, …)` pair."""
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    reservation_id = uuid.uuid4()
    repo = SqlAlchemyPropertyStateTransitionRepository(db_session)
    await repo.add(
        tenant.id, _transition(tenant.id, model.id, metadata={"trigger": "OWNER_BLOCKED"})
    )
    await repo.add(
        tenant.id,
        _transition(
            tenant.id,
            model.id,
            metadata={
                "trigger": "CHECKOUT_TIME_REACHED",
                "reservation_id": str(reservation_id),
            },
        ),
    )

    found = await repo.applied_clock_triggers(tenant.id, [reservation_id])

    assert found == {(reservation_id, "CHECKOUT_TIME_REACHED")}


@pytest.mark.asyncio
async def test_applied_clock_triggers_never_reads_another_tenants_history(db_session) -> None:
    """Rule 1 of `steering/security.md`, on a query whose filter is a JSON expression.

    The `reservation_id` is a UUID the caller supplies, so without the tenant predicate one
    tenant could confirm another's transition and suppress a stall it should have been shown.
    """
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, internal_code="THEIRS")
    reservation_id = uuid.uuid4()
    await SqlAlchemyPropertyStateTransitionRepository(db_session).add(
        tenant_b.id,
        _transition(
            tenant_b.id,
            theirs.id,
            metadata={
                "trigger": "CHECKIN_TIME_REACHED",
                "reservation_id": str(reservation_id),
            },
        ),
    )

    found = await SqlAlchemyPropertyStateTransitionRepository(db_session).applied_clock_triggers(
        tenant_a.id, [reservation_id]
    )

    assert found == set()


@pytest.mark.asyncio
async def test_applied_clock_triggers_does_not_return_an_unasked_reservation(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    asked, other = uuid.uuid4(), uuid.uuid4()
    repo = SqlAlchemyPropertyStateTransitionRepository(db_session)
    for reservation_id in (asked, other):
        await repo.add(
            tenant.id,
            _transition(
                tenant.id,
                model.id,
                metadata={
                    "trigger": "CHECKIN_TIME_REACHED",
                    "reservation_id": str(reservation_id),
                },
            ),
        )

    found = await repo.applied_clock_triggers(tenant.id, [asked])

    assert found == {(asked, "CHECKIN_TIME_REACHED")}


# --- `last_for_property` (`dashboard-api` R3.1, task 3.1) -------------------------------


async def _add_transition(db_session, tenant, model, **overrides) -> PropertyStateTransition:
    transition = _transition(tenant.id, model.id, **overrides)
    await SqlAlchemyPropertyStateTransitionRepository(db_session).add(tenant.id, transition)
    return transition


@pytest.mark.asyncio
async def test_last_for_property_is_none_when_nothing_has_transitioned(db_session) -> None:
    """A property created and never moved: its state is the DDL default and there is no
    transition to date it."""
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")

    found = await SqlAlchemyPropertyStateTransitionRepository(db_session).last_for_property(
        tenant.id, model.id
    )

    assert found is None


@pytest.mark.asyncio
async def test_last_for_property_returns_the_newest_transition(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    await _add_transition(db_session, tenant, model, created_at=datetime(2026, 8, 1, tzinfo=UTC))
    newest = await _add_transition(
        db_session,
        tenant,
        model,
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
        to_state=PropertyOperationalState.AWAITING_CLEANING,
    )
    await _add_transition(db_session, tenant, model, created_at=datetime(2026, 8, 4, tzinfo=UTC))

    found = await SqlAlchemyPropertyStateTransitionRepository(db_session).last_for_property(
        tenant.id, model.id
    )

    assert found is not None
    assert found.id == newest.id
    assert found.to_state is PropertyOperationalState.AWAITING_CLEANING
    assert found.created_at == datetime(2026, 8, 7, tzinfo=UTC)


@pytest.mark.asyncio
async def test_last_for_property_returns_a_domain_entity_with_every_field(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    written = await _add_transition(db_session, tenant, model)

    found = await SqlAlchemyPropertyStateTransitionRepository(db_session).last_for_property(
        tenant.id, model.id
    )

    assert found is not None
    assert isinstance(found, PropertyStateTransition)
    assert (found.from_state, found.to_state) == (written.from_state, written.to_state)
    assert found.triggered_by is written.triggered_by
    assert found.triggered_by_user_id == written.triggered_by_user_id
    assert found.reason == written.reason
    assert found.metadata == {"trigger": "CHECKIN_WINDOW_OPENED"}


@pytest.mark.asyncio
async def test_last_for_property_breaks_a_shared_instant_by_id(db_session) -> None:
    """Transitions are written with the instant the use case decided on, not `now()`, so
    two of one operation can share `created_at` and "the last one" must still be total."""
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    shared = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
    low = uuid.UUID("00000000-0000-4000-8000-000000000001")
    high = uuid.UUID("ffffffff-0000-4000-8000-000000000002")
    # Inserted low-then-high; the reversed order is covered below, so the answer cannot be
    # "whichever went in last" wearing an ordering clause as a disguise.
    await _add_transition(db_session, tenant, model, id=low, created_at=shared)
    await _add_transition(db_session, tenant, model, id=high, created_at=shared)

    found = await SqlAlchemyPropertyStateTransitionRepository(db_session).last_for_property(
        tenant.id, model.id
    )

    assert found is not None and found.id == high


@pytest.mark.asyncio
async def test_the_shared_instant_tiebreak_does_not_depend_on_insertion_order(
    db_session,
) -> None:
    """The other half of the pair the QA panel of section 3 asked for."""
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    shared = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
    low = uuid.UUID("00000000-0000-4000-8000-000000000001")
    high = uuid.UUID("ffffffff-0000-4000-8000-000000000002")
    await _add_transition(db_session, tenant, model, id=high, created_at=shared)
    await _add_transition(db_session, tenant, model, id=low, created_at=shared)

    found = await SqlAlchemyPropertyStateTransitionRepository(db_session).last_for_property(
        tenant.id, model.id
    )

    assert found is not None and found.id == high


@pytest.mark.asyncio
async def test_last_for_property_never_reads_another_tenants_history(db_session) -> None:
    """DoD §28.18, and design D11: `None` outside the tenant is what lets the route answer
    `404` instead of `403`."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, internal_code="THEIRS")
    await _add_transition(db_session, tenant_b, theirs)

    found = await SqlAlchemyPropertyStateTransitionRepository(db_session).last_for_property(
        tenant_a.id, theirs.id
    )

    assert found is None


@pytest.mark.asyncio
async def test_last_for_property_does_not_mix_in_a_sibling_property(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    mine = await _property(db_session, tenant, internal_code="REDES11")
    other = await _property(db_session, tenant, internal_code="PAJARITOS8")
    await _add_transition(
        db_session, tenant, other, created_at=datetime(2026, 8, 9, tzinfo=UTC)
    )
    written = await _add_transition(
        db_session, tenant, mine, created_at=datetime(2026, 8, 1, tzinfo=UTC)
    )

    found = await SqlAlchemyPropertyStateTransitionRepository(db_session).last_for_property(
        tenant.id, mine.id
    )

    assert found is not None and found.id == written.id


# --- `history_for_properties` (`dashboard-occupancy-series` R3, tasks 1.1-1.3) ----------

#: The ISO week the series is drawn over: Monday 2026-08-03 to Sunday 2026-08-09. `WEEK_END`
#: is inclusive **as a calendar date** — the adapter turns it into the instant bound.
WEEK_START = date(2026, 8, 3)
WEEK_END = date(2026, 8, 9)

#: The public surface of the transition repository, named exhaustively rather than as a list
#: of forbidden words. A guard that banned `save`/`update`/`delete` by name would pass for a
#: writer called `record` or `backfill`; pinning the whole set makes *any* new method a
#: failure somebody has to look at.
TRANSITION_REPOSITORY_SURFACE = {
    "add",
    "applied_clock_triggers",
    "last_for_property",
    "history_for_properties",
}


async def _history(db_session, tenant, property_ids, *, start=WEEK_START, end=WEEK_END):
    return await SqlAlchemyPropertyStateTransitionRepository(db_session).history_for_properties(
        tenant.id, property_ids, start, end
    )


@pytest.mark.asyncio
async def test_history_includes_the_transition_the_window_was_entered_with(db_session) -> None:
    """The state a flat carries into Monday has no transition inside the week.

    R3.1: "incluida, si existe, la última transición anterior a `start`". A flat that became
    `OCCUPIED_ESTIMATED` on the Saturday before and never moved again produces nothing at
    all inside the window, and a reader that only saw it would report the flat vacant for
    seven days.
    """
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    entering = await _add_transition(
        db_session,
        tenant,
        model,
        created_at=datetime(2026, 8, 1, 16, 0, tzinfo=UTC),
        to_state=PropertyOperationalState.OCCUPIED_ESTIMATED,
    )

    history = await _history(db_session, tenant, [model.id])

    assert [row.id for row in history[model.id]] == [entering.id]
    assert history[model.id][0].to_state is PropertyOperationalState.OCCUPIED_ESTIMATED


@pytest.mark.asyncio
async def test_history_carries_only_the_last_transition_before_the_window(db_session) -> None:
    """One row, not the whole past: the entering state is the *newest* thing before `start`."""
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    await _add_transition(db_session, tenant, model, created_at=datetime(2026, 7, 12, tzinfo=UTC))
    await _add_transition(db_session, tenant, model, created_at=datetime(2026, 7, 26, tzinfo=UTC))
    newest_before = await _add_transition(
        db_session,
        tenant,
        model,
        created_at=datetime(2026, 8, 2, 23, 0, tzinfo=UTC),
        to_state=PropertyOperationalState.OCCUPIED_ESTIMATED,
    )

    history = await _history(db_session, tenant, [model.id])

    assert [row.id for row in history[model.id]] == [newest_before.id]


@pytest.mark.asyncio
async def test_history_returns_the_windows_transitions_in_chronological_order(db_session) -> None:
    """R3.1's "a lo largo de esa ventana": every row inside `[start, end]`, oldest first.

    Inserted out of order on purpose — chronology must come from the `ORDER BY`, not from the
    sequence the rows happened to be written in.
    """
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    friday = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    monday = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)
    wednesday = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)
    for instant in (friday, monday, wednesday):
        await _add_transition(db_session, tenant, model, created_at=instant)

    history = await _history(db_session, tenant, [model.id])

    assert [row.created_at for row in history[model.id]] == [monday, wednesday, friday]


@pytest.mark.asyncio
async def test_history_puts_the_entering_transition_before_the_windows_own(db_session) -> None:
    """The two statements come back as one chronological sequence, not as two lists a caller
    has to splice."""
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    entering = await _add_transition(
        db_session, tenant, model, created_at=datetime(2026, 8, 1, 16, 0, tzinfo=UTC)
    )
    inside = await _add_transition(
        db_session, tenant, model, created_at=datetime(2026, 8, 6, 8, 0, tzinfo=UTC)
    )

    history = await _history(db_session, tenant, [model.id])

    assert [row.id for row in history[model.id]] == [entering.id, inside.id]


@pytest.mark.asyncio
async def test_history_covers_the_whole_of_the_last_day_and_stops_there(db_session) -> None:
    """`end` is inclusive as a calendar date (R2.4, and the adapter's conversion rule).

    The last second of Sunday belongs to the week; midnight on Monday does not. Getting this
    wrong by one day is invisible in every other test — both bounds still "work", the series
    is just short or long by a day.
    """
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    last_moment = await _add_transition(
        db_session, tenant, model, created_at=datetime(2026, 8, 9, 23, 59, 59, tzinfo=UTC)
    )
    await _add_transition(db_session, tenant, model, created_at=datetime(2026, 8, 10, tzinfo=UTC))

    history = await _history(db_session, tenant, [model.id])

    assert [row.id for row in history[model.id]] == [last_moment.id]


@pytest.mark.asyncio
async def test_history_starts_at_midnight_utc_of_the_first_day(db_session) -> None:
    """The other bound: a transition exactly at `start` is inside the window, not the row
    the property "entered" with."""
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    at_midnight = await _add_transition(
        db_session, tenant, model, created_at=datetime(2026, 8, 3, 0, 0, tzinfo=UTC)
    )

    history = await _history(db_session, tenant, [model.id])

    assert [row.id for row in history[model.id]] == [at_midnight.id]


@pytest.mark.asyncio
async def test_history_omits_a_property_with_nothing_before_or_during_the_window(
    db_session,
) -> None:
    """Dispersed, per `sdd/specs/dashboard-api.md` "Composición por lotes": absent, not
    mapped to an empty sequence.

    Two ways to have no history in a week — never having transitioned at all, and having
    transitioned only *after* it — and both must be absent, because a property whose only row
    is in the future has no state to attribute to the week either.
    """
    tenant = await _tenant(db_session, "TenantA")
    quiet = await _property(db_session, tenant, internal_code="QUIET")
    future_only = await _property(db_session, tenant, internal_code="FUTURE")
    moved = await _property(db_session, tenant, internal_code="MOVED")
    await _add_transition(
        db_session, tenant, future_only, created_at=datetime(2026, 8, 20, tzinfo=UTC)
    )
    await _add_transition(db_session, tenant, moved, created_at=datetime(2026, 8, 5, tzinfo=UTC))

    history = await _history(db_session, tenant, [quiet.id, future_only.id, moved.id])

    assert set(history) == {moved.id}


@pytest.mark.asyncio
async def test_history_never_reads_another_tenants_transitions(db_session) -> None:
    """`steering/backend.md`: "No queries sin tenant scope." Both statements are scoped, so
    neither the entering row nor the window's own can come from a neighbour.

    Asked with the neighbour's own `property_id`, which is the only way the leak could
    happen: the ids arrive already resolved, so a missing `tenant_id` predicate would answer
    with their history in full.
    """
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = await _property(db_session, tenant_b, internal_code="THEIRS")
    await _add_transition(
        db_session, tenant_b, theirs, created_at=datetime(2026, 8, 1, tzinfo=UTC)
    )
    await _add_transition(
        db_session, tenant_b, theirs, created_at=datetime(2026, 8, 5, tzinfo=UTC)
    )

    history = await _history(db_session, tenant_a, [theirs.id])

    assert history == {}


@pytest.mark.asyncio
async def test_history_does_not_mix_a_neighbours_rows_into_its_own_answer(db_session) -> None:
    """The other direction of the same rule: TenantA's series must be exactly TenantA's."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    mine = await _property(db_session, tenant_a, internal_code="MINE")
    theirs = await _property(db_session, tenant_b, internal_code="THEIRS")
    await _add_transition(
        db_session, tenant_b, theirs, created_at=datetime(2026, 8, 4, tzinfo=UTC)
    )
    written = await _add_transition(
        db_session, tenant_a, mine, created_at=datetime(2026, 8, 6, tzinfo=UTC)
    )

    history = await _history(db_session, tenant_a, [mine.id, theirs.id])

    assert set(history) == {mine.id}
    assert [row.id for row in history[mine.id]] == [written.id]


@pytest.mark.asyncio
async def test_history_returns_domain_entities_with_every_field(db_session) -> None:
    """`steering/backend-architecture.md`: the port "habla en términos de entidades de
    dominio, nunca de modelos ORM" — so no `PropertyStateTransitionModel` reaches the
    caller, and `metadata` arrives under its domain name."""
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    written = await _add_transition(db_session, tenant, model)

    history = await _history(db_session, tenant, [model.id])

    (found,) = history[model.id]
    assert isinstance(found, PropertyStateTransition)
    assert (found.id, found.property_id, found.tenant_id) == (
        written.id,
        model.id,
        tenant.id,
    )
    assert (found.from_state, found.to_state) == (written.from_state, written.to_state)
    assert found.triggered_by is written.triggered_by
    assert found.triggered_by_user_id == written.triggered_by_user_id
    assert found.reason == written.reason
    assert found.metadata == {"trigger": "CHECKIN_WINDOW_OPENED"}


@pytest.mark.asyncio
async def test_history_of_no_properties_does_not_query(db_session, test_engine) -> None:
    tenant = await _tenant(db_session, "TenantA")

    with count_statements(test_engine) as log:
        history = await _history(db_session, tenant, [])

    assert history == {}
    assert log.matching("property_state_transitions") == []


@pytest.mark.asyncio
async def test_history_costs_two_statements_whatever_the_portfolio_size(
    db_session, test_engine
) -> None:
    """R3.2: "un número fijo de consultas, independiente del número de viviendas".

    Measured at two sizes in one test rather than against a constant, for the reason
    `tests/dashboard/test_no_n_plus_one.py` records: a `for` calling `last_for_property` per
    property is syntactically identical to the correct code, and only the count tells them
    apart. Comparing the two counts to each other is what asserts "does not grow with N"
    instead of "is under a number I picked" — the equality is asserted first, and the exact
    two of design D2 after it.
    """
    tenant = await _tenant(db_session, "TenantA")
    ids: list[uuid.UUID] = []
    for index in range(5):
        model = await _property(db_session, tenant, internal_code=f"FLAT-{index}")
        # Rows on both sides of `start`, so both statements have something to return and
        # neither can look cheap by finding nothing.
        await _add_transition(
            db_session, tenant, model, created_at=datetime(2026, 8, 1, tzinfo=UTC)
        )
        await _add_transition(
            db_session, tenant, model, created_at=datetime(2026, 8, 5, tzinfo=UTC)
        )
        ids.append(model.id)

    with count_statements(test_engine) as one_log:
        one = await _history(db_session, tenant, ids[:1])
    with count_statements(test_engine) as five_log:
        five = await _history(db_session, tenant, ids)

    assert len(one) == 1 and len(five) == 5
    reads_for_one = len(one_log.matching("from property_state_transitions"))
    reads_for_five = len(five_log.matching("from property_state_transitions"))
    assert reads_for_one == reads_for_five, (
        f"one property cost {reads_for_one} statements and five cost {reads_for_five}; "
        "the reader must batch"
    )
    assert reads_for_five == 2


@pytest.mark.asyncio
async def test_history_writes_nothing_to_the_audit_record(db_session, test_engine) -> None:
    """R3.3: the new method is "puramente de lectura".

    `property_state_transitions` is the audit record of property state (rule 9 of
    `sdd/steering/security.md`), so the series is *derived* from the rows and never repairs,
    backfills or normalises them. Asserted on the SQL that reached the database and on the
    rows afterwards, because a reader that quietly rewrote a row would leave the mapping it
    returns looking perfectly correct.
    """
    tenant = await _tenant(db_session, "TenantA")
    model = await _property(db_session, tenant, internal_code="REDES11")
    await _add_transition(db_session, tenant, model, created_at=datetime(2026, 8, 1, tzinfo=UTC))
    await _add_transition(db_session, tenant, model, created_at=datetime(2026, 8, 5, tzinfo=UTC))
    snapshot = await _stored_transitions(db_session)

    with count_statements(test_engine) as log:
        await _history(db_session, tenant, [model.id])

    for verb in ("insert into property_state_transitions", "update property_state_transitions"):
        assert log.matching(verb) == []
    assert log.matching("delete from property_state_transitions") == []
    assert await _stored_transitions(db_session) == snapshot


async def _stored_transitions(db_session) -> list[tuple]:
    rows = await db_session.execute(
        select(PropertyStateTransitionModel).order_by(PropertyStateTransitionModel.id)
    )
    return [
        (
            model.id,
            model.tenant_id,
            model.property_id,
            model.from_state,
            model.to_state,
            model.triggered_by,
            model.triggered_by_user_id,
            model.reason,
            model.metadata_,
            model.created_at,
        )
        for model in rows.scalars()
    ]


def test_the_transition_port_still_has_add_and_no_new_writer() -> None:
    """R3.3: "SHALL NOT modificar `PropertyStateTransitionRepository.add`".

    Two halves. `add`'s signature is pinned against the port's own, so a change to either
    that did not reach the other shows up here; and the repository's public surface is pinned
    exhaustively, so the next method — reader or writer — cannot arrive unnoticed. The
    exhaustive form is deliberate: a guard listing `save`/`update`/`delete` by name would let
    a writer called `backfill` straight through.
    """
    port = inspect.signature(PropertyStateTransitionRepository.add)
    adapter = inspect.signature(SqlAlchemyPropertyStateTransitionRepository.add)
    assert list(port.parameters) == ["self", "tenant_id", "transition"]
    assert port == adapter

    surface = {
        name
        for name in dir(SqlAlchemyPropertyStateTransitionRepository)
        if not name.startswith("_")
    }
    assert surface == TRANSITION_REPOSITORY_SURFACE
    assert surface == {
        name for name in dir(PropertyStateTransitionRepository) if not name.startswith("_")
    }
