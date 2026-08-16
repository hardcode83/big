"""Who may do what with the inbox (R7.2, design D17).

`tests/test_route_authorization.py` proves every route *declares* a permission; this proves the
declaration is the right one, per role, over HTTP. The interesting row is `TENANT_OWNER`: she
reads and does not operate, which was weighed against the precedent of
`MANAGE_GUEST_ACCESS_TOKENS` and resolved for symmetry with `reservations` and `properties` in
the design gate of 2026-08-16. Its declared consequence — `MessageSenderType.OWNER` has no
writer in this change — is pinned in `test_use_cases.py`.
"""

import uuid

import pytest

from app.auth.domain.enums import UserRole
from app.auth.domain.policy import ROLE_PERMISSIONS, Permission
from tests.messaging.conftest import (  # noqa: F401
    api,
    auth_header,
    seed_conversation,
    seed_property,
    seed_tenant,
    world,
)

CONVERSATIONS = "/api/v1/conversations"


# --- The catalogue itself (R7.2) ---------------------------------------------------------


def test_the_two_permissions_are_shared_out_as_the_design_says() -> None:
    read = Permission.READ_CONVERSATIONS
    manage = Permission.MANAGE_CONVERSATIONS

    assert read in ROLE_PERMISSIONS[UserRole.PROPERTY_MANAGER]
    assert manage in ROLE_PERMISSIONS[UserRole.PROPERTY_MANAGER]

    assert read in ROLE_PERMISSIONS[UserRole.TENANT_OWNER]
    assert manage not in ROLE_PERMISSIONS[UserRole.TENANT_OWNER]

    for role in (UserRole.CLEANER, UserRole.TECHNICIAN, UserRole.SUPER_ADMIN):
        assert read not in ROLE_PERMISSIONS[role]
        assert manage not in ROLE_PERMISSIONS[role]


def test_managing_implies_reading() -> None:
    """A manager who could write and not read would be able to escalate a conversation she
    cannot open — the same bundling every other read/manage pair in the catalogue uses."""
    assert (
        Permission.READ_CONVERSATIONS in ROLE_PERMISSIONS[UserRole.PROPERTY_MANAGER]
    )


# --- Reading (R7.2) ----------------------------------------------------------------------


@pytest.mark.parametrize("actor", ["manager", "owner"])
@pytest.mark.asyncio
async def test_the_roles_that_read_can_list(api, world, actor) -> None:
    response = await api.get(
        CONVERSATIONS, headers=auth_header(api, getattr(world, actor))
    )

    assert response.status_code == 200


@pytest.mark.parametrize("actor", ["cleaner", "technician"])
@pytest.mark.asyncio
async def test_the_roles_that_do_not_read_are_refused(api, world, actor) -> None:
    """A guest's conversation is not part of doing a cleaning or a repair."""
    response = await api.get(
        CONVERSATIONS, headers=auth_header(api, getattr(world, actor))
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reading_a_thread_needs_the_read_permission(api, world, db_session) -> None:
    conversation = await seed_conversation(db_session, world.tenant, world.property)

    allowed = await api.get(
        f"{CONVERSATIONS}/{conversation.id}/messages",
        headers=auth_header(api, world.owner),
    )
    refused = await api.get(
        f"{CONVERSATIONS}/{conversation.id}/messages",
        headers=auth_header(api, world.cleaner),
    )

    assert allowed.status_code == 200
    assert refused.status_code == 403


# --- Operating (R7.2, D17) ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_owner_cannot_open_a_conversation(api, world) -> None:
    """D17: she sees what her guests are saying; she does not answer them."""
    response = await api.post(
        CONVERSATIONS,
        json={"property_id": str(world.property.id), "channel": "MANUAL"},
        headers=auth_header(api, world.owner),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_owner_cannot_write_a_message(api, world, db_session) -> None:
    """The route-level half of why `MessageSenderType.OWNER` has no writer in this change."""
    conversation = await seed_conversation(db_session, world.tenant, world.property)

    response = await api.post(
        f"{CONVERSATIONS}/{conversation.id}/messages",
        json={"content": "Yo me encargo"},
        headers=auth_header(api, world.owner),
    )

    assert response.status_code == 403


@pytest.mark.parametrize("action", ["escalate", "resolve"])
@pytest.mark.asyncio
async def test_the_owner_cannot_escalate_or_resolve(
    api, world, db_session, action
) -> None:
    conversation = await seed_conversation(db_session, world.tenant, world.property)

    response = await api.post(
        f"{CONVERSATIONS}/{conversation.id}/{action}",
        headers=auth_header(api, world.owner),
    )

    assert response.status_code == 403


@pytest.mark.parametrize("actor", ["cleaner", "technician"])
@pytest.mark.asyncio
async def test_no_operational_role_can_write_a_message(
    api, world, db_session, actor
) -> None:
    conversation = await seed_conversation(db_session, world.tenant, world.property)

    response = await api.post(
        f"{CONVERSATIONS}/{conversation.id}/messages",
        json={"content": "hola"},
        headers=auth_header(api, getattr(world, actor)),
    )

    assert response.status_code == 403


# --- Anonymous (R7.2) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("post", ""),
        ("get", "/{id}"),
        ("get", "/{id}/messages"),
        ("post", "/{id}/messages"),
        ("post", "/{id}/escalate"),
        ("post", "/{id}/resolve"),
    ],
)
@pytest.mark.asyncio
async def test_every_route_refuses_an_anonymous_caller(api, method, path) -> None:
    """**There is no anonymous door into this module**, and that is load-bearing beyond
    tidiness: the human actor of D12 is what lets an incident derived from a conversation
    carry `actor_user_id`, and therefore what keeps rule 9 of `steering/security.md` free of a
    new exception. An unauthenticated route here would quietly break that argument."""
    url = f"{CONVERSATIONS}{path.replace('{id}', str(uuid.uuid4()))}"

    response = await api.request(url=url, method=method.upper(), json={})

    assert response.status_code == 401
