"""The two administration endpoints of `reservations-webhooks` R2 (tasks 1.6, design D3).

What is tested here and not in `test_webhook_provisioning.py`: the transport half — who may call
these at all (R2.5), what the response is allowed to carry (R2.3), and that the URL handed to the
operator is one this app actually serves.
"""

import uuid

import pytest

from app.auth.domain.enums import UserRole
from app.core.crypto import encrypt
from app.integrations.api.schemas import WEBHOOK_RECEIVER_PREFIX
from app.integrations.domain.entities import WebhookEndpoint
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.webhook_auth import (
    generate_webhook_token,
    hash_webhook_token,
)
from app.integrations.infrastructure.repositories import (
    SqlAlchemyWebhookEndpointRepository,
)
from tests.integrations.conftest import auth_header
from tests.route_walk import flatten_routes

ENDPOINTS = "/api/v1/integrations/webhook-endpoints"
HEADER_NAME = "X-Beds24-Secret"
CREATE_BODY = {"provider": PMSProvider.BEDS24.value, "header_name": HEADER_NAME}


def _owner(users_by_role_a):
    return users_by_role_a[UserRole.TENANT_OWNER]


def _endpoint(tenant_id: uuid.UUID) -> WebhookEndpoint:
    return WebhookEndpoint(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider=PMSProvider.BEDS24,
        token_hash=hash_webhook_token(generate_webhook_token()),
        header_name=HEADER_NAME,
        header_secret=encrypt("theirs"),
    )


async def _create(api, user, body=None):
    return await api.post(ENDPOINTS, json=body or CREATE_BODY, headers=auth_header(api, user))


# --- RBAC (R2.5) ---


@pytest.mark.asyncio
async def test_creating_without_authentication_is_refused(api) -> None:
    response = await api.post(ENDPOINTS, json=CREATE_BODY)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rotating_without_authentication_is_refused(api) -> None:
    response = await api.post(f"{ENDPOINTS}/{uuid.uuid4()}/rotate")

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.PROPERTY_MANAGER, UserRole.CLEANER, UserRole.TECHNICIAN]
)
async def test_a_role_without_tenant_settings_cannot_mint_material(
    api, users_by_role_a, role
) -> None:
    """The manager is included on purpose, and is the interesting one.

    They operate the PMS integration — they import the CSV next door with
    `MANAGE_RESERVATIONS` — so "they run the integration, let them provision it" is the
    plausible relaxation. Minting this material decides who may write into the tenant from the
    internet, for every property at once, which PRD §6 puts with the owner.
    """
    response = await _create(api, users_by_role_a[role])

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_owner_can_mint_material(api, users_by_role_a) -> None:
    response = await _create(api, _owner(users_by_role_a))

    assert response.status_code == 201


# --- What the response carries, and what it must not (R2.3) ---


@pytest.mark.asyncio
async def test_the_response_carries_both_secrets_exactly_once(api, users_by_role_a) -> None:
    body = (await _create(api, _owner(users_by_role_a))).json()

    assert body["header_secret"]
    assert body["header_name"] == HEADER_NAME
    assert body["provider"] == PMSProvider.BEDS24.value
    # The token is IN the URL — that is the whole of rule 12(b) — so this is what "returned once"
    # means for it. The URL is therefore as secret as the secret beside it.
    assert body["webhook_url"].startswith("http://test")
    assert f"{WEBHOOK_RECEIVER_PREFIX}/beds24/" in body["webhook_url"]
    assert body["notice"]


@pytest.mark.asyncio
async def test_the_minted_url_names_a_path_this_app_will_serve(api, users_by_role_a) -> None:
    """The one thing a constant duplicated out of `main.API_V1_PREFIX` can get wrong.

    Until `webhooks_router.py` exists (task 2.5) there is no route to compare against, so this
    asserts the weaker half that IS checkable today: the prefix the operator is handed is the
    prefix every other v1 route is mounted under. When the receiving route lands, this tightens
    to an exact match against it.
    """
    body = (await _create(api, _owner(users_by_role_a))).json()
    routes, _ = flatten_routes(api._transport.app)  # type: ignore[attr-defined]

    version_prefix = WEBHOOK_RECEIVER_PREFIX.rsplit("/", 1)[0]
    assert any(path.startswith(f"{version_prefix}/") for path, _ in routes)
    assert version_prefix in body["webhook_url"]


@pytest.mark.asyncio
async def test_a_malformed_header_name_is_refused(api, users_by_role_a) -> None:
    """A header name is a token: no spaces, no colons, no newlines."""
    response = await _create(
        api,
        _owner(users_by_role_a),
        body={"provider": PMSProvider.BEDS24.value, "header_name": "X-Bad: injected\r\n"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_provider_is_refused(api, users_by_role_a) -> None:
    response = await _create(
        api,
        _owner(users_by_role_a),
        body={"provider": "OCTORATE", "header_name": HEADER_NAME},
    )

    assert response.status_code == 422


# --- Conflict and absence ---


@pytest.mark.asyncio
async def test_a_second_endpoint_for_the_same_provider_is_a_conflict(
    api, users_by_role_a
) -> None:
    first = (await _create(api, _owner(users_by_role_a))).json()

    response = await _create(api, _owner(users_by_role_a))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    # The live material is untouched: a 409 that had already overwritten would be worse than a
    # 201, because the operator would believe nothing happened.
    rotated = await api.post(
        f"{ENDPOINTS}/{first['id']}/rotate",
        headers=auth_header(api, _owner(users_by_role_a)),
    )
    assert rotated.status_code == 200


@pytest.mark.asyncio
async def test_rotating_an_unknown_endpoint_is_a_404(api, users_by_role_a) -> None:
    response = await api.post(
        f"{ENDPOINTS}/{uuid.uuid4()}/rotate",
        headers=auth_header(api, _owner(users_by_role_a)),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_tenant_gets_the_same_404_for_another_tenants_endpoint(
    api, db_session, tenant_b, users_by_role_a
) -> None:
    """Rule 1: indistinguishable from an id that does not exist anywhere.

    The neighbour's row is seeded through the repository rather than through a second HTTP call,
    which is the shape `tests/cleaning/test_templates_api.py` already uses and is not merely
    stylistic: the suite hands every request the same session, and `bind_session_to_tenant` is
    one-way, so authenticating as tenant B first would make tenant A's own user unreadable and
    the test would pass with a 401 that proves nothing.
    """
    theirs = _endpoint(tenant_b.id)
    await SqlAlchemyWebhookEndpointRepository(db_session).upsert(tenant_b.id, theirs)
    await db_session.flush()

    response = await api.post(
        f"{ENDPOINTS}/{theirs.id}/rotate",
        headers=auth_header(api, _owner(users_by_role_a)),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rotation_returns_fresh_material(api, users_by_role_a) -> None:
    owner = _owner(users_by_role_a)
    created = (await _create(api, owner)).json()

    rotated = await api.post(
        f"{ENDPOINTS}/{created['id']}/rotate", headers=auth_header(api, owner)
    )

    assert rotated.status_code == 200
    body = rotated.json()
    assert body["id"] == created["id"]
    assert body["webhook_url"] != created["webhook_url"]
    assert body["header_secret"] != created["header_secret"]
