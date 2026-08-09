"""`GET /api/v1/properties/{id}/state` (`dashboard-api` R3, task 3.2).

The point of these tests is that the endpoint **reads**: what it answers is what
`PropertyStateMachine` left behind, never a recomputation (R3.2).
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.auth.domain.enums import UserRole
from app.properties.domain.entities import PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState, StateTransitionTriggeredBy
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyStateTransitionRepository,
)
from tests.properties.conftest import auth_header

READERS = {UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER}


async def _property(db_session, tenant, internal_code: str = "REDES11") -> PropertyModel:
    model = PropertyModel(
        tenant_id=tenant.id, name="Redes 11", internal_code=internal_code, max_guests=4
    )
    db_session.add(model)
    await db_session.flush()
    return model


async def _transition(
    db_session,
    tenant,
    model: PropertyModel,
    *,
    to_state: PropertyOperationalState,
    created_at: datetime,
    from_state: PropertyOperationalState | None = PropertyOperationalState.VACANT_READY,
) -> PropertyStateTransition:
    transition = PropertyStateTransition(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        property_id=model.id,
        from_state=from_state,
        to_state=to_state,
        triggered_by=StateTransitionTriggeredBy.SYSTEM,
        created_at=created_at,
    )
    await SqlAlchemyPropertyStateTransitionRepository(db_session).add(tenant.id, transition)
    return transition


def _url(model: PropertyModel) -> str:
    return f"/api/v1/properties/{model.id}/state"


# --- shape (R3.1) -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_answers_the_state_and_the_instant_and_nothing_else(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    model = await _property(db_session, tenant_a)

    response = await api.get(
        _url(model), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.status_code == 200
    assert set(response.json()) == {"current_operational_state", "last_transition_at"}


@pytest.mark.asyncio
async def test_a_property_that_never_moved_reports_its_default_state_and_no_instant(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """Creation is not a transition (`PropertyRepository.add` documents why), so there is
    genuinely no instant rather than one we failed to find."""
    model = await _property(db_session, tenant_a)

    body = (
        await api.get(
            _url(model), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
        )
    ).json()

    assert body["current_operational_state"] == "VACANT_READY"
    assert body["last_transition_at"] is None


@pytest.mark.asyncio
async def test_the_response_matches_what_a_real_transition_left_behind(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """The assertion the task asks for: the endpoint agrees with the history, because it
    reads it rather than deriving anything."""
    model = await _property(db_session, tenant_a)
    moment = datetime(2026, 8, 7, 9, 30, tzinfo=UTC)
    await _transition(
        db_session,
        tenant_a,
        model,
        to_state=PropertyOperationalState.AWAITING_CLEANING,
        created_at=moment,
    )
    # The column the machine writes alongside the transition.
    model.current_operational_state = PropertyOperationalState.AWAITING_CLEANING
    await db_session.flush()

    body = (
        await api.get(
            _url(model), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
        )
    ).json()

    assert body["current_operational_state"] == "AWAITING_CLEANING"
    assert datetime.fromisoformat(body["last_transition_at"]) == moment


@pytest.mark.asyncio
async def test_it_reports_the_newest_transition_when_there_are_several(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    model = await _property(db_session, tenant_a)
    await _transition(
        db_session,
        tenant_a,
        model,
        to_state=PropertyOperationalState.AWAITING_CHECKIN,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    await _transition(
        db_session,
        tenant_a,
        model,
        to_state=PropertyOperationalState.OCCUPIED_ESTIMATED,
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
    )

    body = (
        await api.get(
            _url(model), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
        )
    ).json()

    assert datetime.fromisoformat(body["last_transition_at"]) == datetime(
        2026, 8, 6, tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_the_state_is_read_from_the_column_and_not_derived_from_the_history(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R3.2: "SHALL NOT reimplementar la resolución de estado en la capa de lectura".

    The two are deliberately made to disagree — which production never does, because every
    writer persists both in one transaction (rule 9 of `steering/security.md`) — so that the
    assertion can only pass if the endpoint reports the column. A version that recomputed
    from the transition history would answer `AWAITING_CLEANING` here.
    """
    model = await _property(db_session, tenant_a)
    await _transition(
        db_session,
        tenant_a,
        model,
        to_state=PropertyOperationalState.AWAITING_CLEANING,
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
    )

    body = (
        await api.get(
            _url(model), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
        )
    ).json()

    assert body["current_operational_state"] == "VACANT_READY"
    assert body["last_transition_at"] is not None


def test_the_read_layer_cannot_reach_the_state_resolver_at_all() -> None:
    """R3.2: "SHALL NOT reimplementar la resolución de estado en la capa de lectura".

    The QA panel of section 3 named the gap the test above cannot cover: it manufactures a
    disagreement between column and history, which production never produces, so it proves
    the current code reads the column but would keep passing if a future change *added* a
    `ContextualStateResolver` call to "refresh" a state that looked stale — column and
    history would still agree.

    This closes it from the other side, statically: the module that serves this route must
    not import the resolver or the machine. An AST check rather than a grep, so the word
    appearing in a docstring — as it does, several times, explaining why it is absent —
    cannot satisfy or break it.
    """
    import ast
    from pathlib import Path

    module = Path(__file__).resolve().parents[2] / "app/properties/application/property_admin.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)

    forbidden = {
        name
        for name in imported
        if "state_resolution" in name
        or name.endswith("ContextualStateResolver")
        or name.endswith("PropertyStateMachine")
    }
    assert not forbidden, (
        f"property_admin.py imports {sorted(forbidden)}; the read layer reports the state "
        "the machine wrote, it does not resolve one"
    )


@pytest.mark.asyncio
async def test_the_state_literal_is_canonical_and_untranslated(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R5.5: `PropertyOperationalState` travels as the exact PRD value."""
    model = await _property(db_session, tenant_a)

    body = (
        await api.get(
            _url(model), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
        )
    ).json()

    assert body["current_operational_state"] in {
        state.value for state in PropertyOperationalState
    }


# --- 404, indistinguishable (R3.3) ------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_property_and_a_neighbours_answer_the_very_same_404(
    api, users_by_role_a, property_b
) -> None:
    headers = auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])

    unknown = await api.get(f"/api/v1/properties/{uuid.uuid4()}/state", headers=headers)
    foreign = await api.get(_url(property_b), headers=headers)

    assert unknown.status_code == foreign.status_code == 404
    assert unknown.json() == foreign.json()


@pytest.mark.asyncio
async def test_a_neighbours_property_stays_404_even_with_a_transition_history(
    api, db_session, tenant_b, users_by_role_a, property_b
) -> None:
    """A history of its own must not turn the `404` into a `200` with someone else's state.

    **What this proves, precisely** (the tenancy panel of section 3 was right that the first
    version of this docstring overclaimed): the use case short-circuits on
    `PropertyRepository.get` returning `None` and never reaches `last_for_property`, so this
    exercises the property-level check with a neighbour that has something worth leaking —
    not the tenant scoping of the transition read. That scoping is proven where it can be:
    `tests/properties/test_repositories.py::
    test_last_for_property_never_reads_another_tenants_history`, against an unbound session,
    so the explicit `WHERE tenant_id` carries the assertion rather than the global filter.
    """
    await _transition(
        db_session,
        tenant_b,
        property_b,
        to_state=PropertyOperationalState.CRITICAL_INCIDENT,
        created_at=datetime(2026, 8, 3, tzinfo=UTC),
    )

    response = await api.get(
        _url(property_b), headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.status_code == 404
    assert "CRITICAL_INCIDENT" not in response.text


# --- authorisation (R3.4) ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_refuses_an_anonymous_request(api, db_session, tenant_a) -> None:
    model = await _property(db_session, tenant_a)

    assert (await api.get(_url(model))).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole))
async def test_only_the_property_readers_may_call_it(
    api, db_session, tenant_a, users_by_role_a, role: UserRole
) -> None:
    model = await _property(db_session, tenant_a)

    response = await api.get(_url(model), headers=auth_header(api, users_by_role_a[role]))

    assert response.status_code == (200 if role in READERS else 403)
