"""The two provisioning endpoints of section 6 (`whatsapp-cloud-adapter` R6.1-R6.3, task 6.5).

What is tested here and not in `test_whatsapp_provisioning.py`: the transport half — who may
call these at all, and what status code each outcome answers with. The application-layer
promises (validated property, database-enforced global uniqueness, the audit row) are that
file's job; testing them again through HTTP would only add a way to pass because a router
happened to filter something.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging.domain.entities import WhatsAppPhoneNumberAssociation
from app.messaging.infrastructure.repositories import (
    SqlAlchemyWhatsAppPhoneNumberRepository,
)
from tests.messaging.conftest import auth_header, seed_property, seed_tenant

ENDPOINT = "/api/v1/messaging/whatsapp-phone-number"
RELEASE_ENDPOINT = f"{ENDPOINT}/release"


async def _associate(api, user, property_id, *, phone_number_id="15550001", body=None):
    return await api.post(
        ENDPOINT,
        json=body
        or {
            "phone_number_id": phone_number_id,
            "default_property_id": str(property_id),
        },
        headers=auth_header(api, user),
    )


async def _release(api, user):
    return await api.post(RELEASE_ENDPOINT, headers=auth_header(api, user))


# --- RBAC (R6.1, R6.3) -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_associating_without_authentication_is_refused(api, world) -> None:
    response = await api.post(
        ENDPOINT,
        json={"phone_number_id": "15550001", "default_property_id": str(world.property.id)},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_releasing_without_authentication_is_refused(api) -> None:
    response = await api.post(RELEASE_ENDPOINT)

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role_attr", ["manager", "cleaner", "technician"]
)
async def test_a_role_without_tenant_settings_cannot_associate(
    api, world, role_attr
) -> None:
    user = getattr(world, role_attr)

    response = await _associate(api, user, world.property.id)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_role_without_tenant_settings_cannot_release(api, world) -> None:
    response = await _release(api, world.manager)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_owner_can_associate(api, world) -> None:
    response = await _associate(api, world.owner, world.property.id)

    assert response.status_code == 201


# --- The response and its shape (R6.1) --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_response_carries_the_association(api, world) -> None:
    body = (await _associate(api, world.owner, world.property.id)).json()

    assert body["phone_number_id"] == "15550001"
    assert body["default_property_id"] == str(world.property.id)
    assert uuid.UUID(body["id"])


@pytest.mark.asyncio
async def test_associating_with_a_property_of_another_tenant_is_a_422(
    api, db_session, world
) -> None:
    other_tenant = await seed_tenant(db_session, "TenantB")
    other_property = await seed_property(db_session, other_tenant, "PAJARITOS8")

    response = await _associate(api, world.owner, other_property.id)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_property_is_a_422(api, world) -> None:
    response = await _associate(api, world.owner, uuid.uuid4())

    assert response.status_code == 422


# --- Conflict and re-association (R6.2, R6.3) -------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_tenant_claiming_the_same_number_is_a_conflict(
    api, db_session, test_engine, world
) -> None:
    """Tenant B's association is seeded through the repository, not a second authenticated
    HTTP call: the suite hands every request the same session, and binding it to a tenant is
    one-way (the same reason `test_a_tenant_gets_the_same_404_for_another_tenants_endpoint`
    in `test_webhook_endpoints_api.py` seeds its neighbour that way) — a second `_associate`
    call authenticating as tenant B would try to re-bind a session already bound to tenant A.

    **The post-request assertions use a fresh, unmarked session, not `db_session`.** Unlike
    the root `conftest.py`'s `request_session_override`, this module's own `api` fixture never
    clears the tenant marker between requests (it is a plain `yield db_session`, no `finally`)
    — so once `world.owner`'s request marks `db_session` to tenant A, the global tenant filter
    of `app/core/db.py` would silently AND a `tenant_id = <tenant A>` predicate onto a read
    for tenant B's row, which is exactly the wrong kind of "it still isn't there" a security
    test must not produce by accident.
    """
    other_tenant = await seed_tenant(db_session, "TenantB")
    other_property = await seed_property(db_session, other_tenant, "PAJARITOS8")
    # Captured now: after `db_session.commit()` the objects stay usable here
    # (`expire_on_commit=False`), but the fresh session opened below is a different identity
    # map and needs the plain UUIDs, not these ORM instances.
    other_tenant_id = other_tenant.id
    world_tenant_id = world.tenant.id
    theirs = WhatsAppPhoneNumberAssociation(
        id=uuid.uuid4(),
        tenant_id=other_tenant_id,
        phone_number_id="15550001",
        display_phone_number=None,
        default_property_id=other_property.id,
    )
    await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).upsert(other_tenant_id, theirs)
    # Committed, not just flushed: the conflicting request below fails at the database and
    # aborts the current Postgres transaction, so this fixture data must already be durable
    # before that happens — same precedent as `test_pipeline_atomicity.py`'s failure tests.
    await db_session.commit()

    response = await _associate(api, world.owner, world.property.id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"

    async with AsyncSession(test_engine) as fresh:
        # The live association is untouched, and tenant A got none.
        still_theirs = await SqlAlchemyWhatsAppPhoneNumberRepository(fresh).find_for_tenant(
            other_tenant_id
        )
        assert still_theirs is not None
        assert still_theirs.id == theirs.id
        assert (
            await SqlAlchemyWhatsAppPhoneNumberRepository(fresh).find_for_tenant(
                world_tenant_id
            )
        ) is None


@pytest.mark.asyncio
async def test_re_associating_replaces_this_tenants_own_number(api, world) -> None:
    first = (await _associate(api, world.owner, world.property.id)).json()

    second = await _associate(
        api,
        world.owner,
        world.property.id,
        body={
            "phone_number_id": "15550002",
            "default_property_id": str(world.property.id),
        },
    )

    assert second.status_code == 201
    body = second.json()
    assert body["id"] == first["id"]
    assert body["phone_number_id"] == "15550002"


# --- Release (R6.3) ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_owner_can_release(api, world) -> None:
    await _associate(api, world.owner, world.property.id)

    response = await _release(api, world.owner)

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_releasing_with_nothing_to_release_is_a_404(api, world) -> None:
    response = await _release(api, world.owner)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_releasing_actually_clears_the_row_so_the_same_tenant_can_re_associate(
    api, db_session, world
) -> None:
    """The row-level, cross-tenant version of "releasing frees the number" is
    `test_releasing_frees_the_number_for_another_tenant` in `test_whatsapp_provisioning.py` —
    a second authenticated HTTP call as a different tenant cannot be driven from here (see the
    conflict test above), so this checks the same effect the one HTTP call CAN observe: after
    a `204`, the row is really gone, not merely reported gone.
    """
    await _associate(api, world.owner, world.property.id)
    release_response = await _release(api, world.owner)
    assert release_response.status_code == 204
    assert (
        await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).find_for_tenant(
            world.tenant.id
        )
    ) is None

    response = await _associate(api, world.owner, world.property.id)

    assert response.status_code == 201
