"""R1 — the checklist template endpoints, end to end over ASGI."""

import json
import uuid

import pytest

from app.auth.domain.enums import UserRole
from app.cleaning.domain.value_objects import MAX_ITEMS, MAX_LABEL_LENGTH
from app.core.http_limits import JSON_BODY_MAX_BYTES
from tests.cleaning.conftest import auth_header, insert_property, insert_template

TEMPLATES = "/api/v1/cleaning-checklist-templates"


@pytest.mark.asyncio
async def test_manager_creates_a_template(api, users_by_role_a, template_payload):
    """R1.1 names `PROPERTY_MANAGER` **and** `TENANT_OWNER` — PRD §6 puts the manager in
    charge of cleaning, and a tenant whose owner never logs in still needs a template."""
    response = await api.post(
        TEMPLATES,
        json=template_payload(),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_owner_creates_a_template(api, users_by_role_a, template_payload):
    response = await api.post(
        TEMPLATES,
        json=template_payload(),
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Estándar"
    assert body["property_id"] is None
    assert body["active"] is True


@pytest.mark.asyncio
async def test_creating_a_property_scoped_template(
    api, users_by_role_a, property_a, template_payload
):
    response = await api.post(
        TEMPLATES,
        json=template_payload(property_id=str(property_a.id)),
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert response.status_code == 201
    assert response.json()["property_id"] == str(property_a.id)


@pytest.mark.asyncio
async def test_a_property_of_another_tenant_answers_404(
    api, users_by_role_a, property_b, template_payload
):
    """R7.3 — indistinguishable from a property that does not exist."""
    response = await api.post(
        TEMPLATES,
        json=template_payload(property_id=str(property_b.id)),
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert response.status_code == 404
    unknown = await api.post(
        TEMPLATES,
        json=template_payload(property_id=str(uuid.uuid4())),
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )
    assert unknown.status_code == 404
    assert unknown.json() == response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "items",
    [
        [{"item_id": "a", "label": "A"}, {"item_id": "a", "label": "B"}],
        [{"item_id": "a/b", "label": "A"}],
        [{"item_id": "x" * 101, "label": "A"}],
    ],
)
async def test_invalid_template_content_is_rejected(api, users_by_role_a, template_payload, items):
    """R1.2 — 422 in the PRD §23 envelope, and nothing written."""
    response = await api.post(
        TEMPLATES,
        json=template_payload(items=items),
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert response.status_code == 422
    assert "error" in response.json()

    listing = await api.get(
        TEMPLATES, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )
    assert listing.json()["total"] == 0


@pytest.mark.asyncio
async def test_an_unknown_body_field_is_refused(api, users_by_role_a, template_payload):
    response = await api.post(
        TEMPLATES,
        json=template_payload(tenant_id=str(uuid.uuid4())),
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_listing_is_scoped_to_the_tenant(
    api, db_session, tenant_a, tenant_b, users_by_role_a, template_a, template_b
):
    response = await api.get(
        TEMPLATES, headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [row["id"] for row in body["data"]] == [str(template_a.id)]


@pytest.mark.asyncio
async def test_listing_paginates(api, db_session, tenant_a, users_by_role_a):
    for index in range(3):
        await insert_template(db_session, tenant_a, name=f"t{index}")

    response = await api.get(
        f"{TEMPLATES}?page=1&per_page=2",
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    body = response.json()
    assert body["total"] == 3
    assert body["per_page"] == 2
    assert body["total_pages"] == 2
    assert len(body["data"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["?per_page=101", "?page=0", "?page=100001"])
async def test_pagination_bounds_are_enforced(api, users_by_role_a, query):
    response = await api.get(
        f"{TEMPLATES}{query}",
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "read", "write"),
    [
        (UserRole.SUPER_ADMIN, 403, 403),
        (UserRole.TENANT_OWNER, 200, 201),
        (UserRole.PROPERTY_MANAGER, 200, 201),
        (UserRole.CLEANER, 403, 403),
        (UserRole.TECHNICIAN, 403, 403),
    ],
)
async def test_authorization_matrix(api, users_by_role_a, template_payload, role, read, write):
    """R7.4 — every role, both endpoints, per design D7."""
    headers = auth_header(api, users_by_role_a[role])

    assert (await api.get(TEMPLATES, headers=headers)).status_code == read
    assert (
        await api.post(TEMPLATES, json=template_payload(), headers=headers)
    ).status_code == write


@pytest.mark.asyncio
async def test_both_endpoints_require_authentication(api, template_payload):
    assert (await api.get(TEMPLATES)).status_code == 401
    assert (await api.post(TEMPLATES, json=template_payload())).status_code == 401


@pytest.mark.asyncio
async def test_the_body_is_capped_before_authentication(api):
    """An anonymous oversized body must be refused with 413, not read in full then 401.

    `MaxBodySizeMiddleware` is the only layer that sees the request before FastAPI reads the
    body, which is before `require(...)` runs. Raised by the security panel of sections 2-3
    after measuring a ~50 MB anonymous POST being received in full.
    """
    # Sized from the constant rather than hardcoded, so raising the ceiling cannot silently
    # turn this into a test of the 401 path — which is exactly what happened when the limit
    # went from 256 KiB to 1 MiB.
    per_item = 240
    count = (JSON_BODY_MAX_BYTES // per_item) + 500
    oversized = {
        "name": "x",
        "items": [{"item_id": f"i{n}", "label": "L" * 200} for n in range(count)],
        "required_photos": [],
    }
    assert len(json.dumps(oversized).encode()) > JSON_BODY_MAX_BYTES

    response = await api.post(TEMPLATES, json=oversized)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.asyncio
async def test_the_largest_schema_valid_template_is_accepted(api, users_by_role_a):
    """The middleware ceiling and the validator must agree about what is legal.

    The worst case is not ASCII: `json.dumps` escapes non-ASCII by default, so 200 items with
    200-character accented labels is ~338 KB — which a 256 KiB ceiling refused with a size
    error where R1.2 promises a validation answer. Measured by the security panel of
    sections 2-3; this test is what keeps `JSON_BODY_MAX_BYTES` tied to the schema maximum.
    """
    payload = {
        "name": "Máximo",
        "items": [
            {"item_id": f"i{n}", "label": "á" * MAX_LABEL_LENGTH, "required": False}
            for n in range(MAX_ITEMS)
        ],
        "required_photos": [],
    }

    response = await api.post(
        TEMPLATES, json=payload, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_created_template_is_readable_afterwards(
    api, db_session, tenant_a, users_by_role_a, template_payload
):
    """The commit boundary really is the use case: a second request sees the row."""
    other = await insert_property(db_session, tenant_a, code="OTHER1")
    created = await api.post(
        TEMPLATES,
        json=template_payload(property_id=str(other.id), name="Solo esta"),
        headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER]),
    )

    listing = await api.get(
        TEMPLATES, headers=auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])
    )
    assert created.json()["id"] in [row["id"] for row in listing.json()["data"]]
