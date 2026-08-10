import pytest

from app.auth.domain.enums import UserRole
from app.core.config import settings
from tests.auth.conftest import auth_header, insert_user


VALID_PROVENANCE = {
    "app_provenance_repository_url": "https://github.com/example/project",
    "app_provenance_pull_request_number": "123",
    "app_provenance_commit_sha": "a" * 40,
    "app_provenance_actions_run_id": "456",
}


def set_provenance(monkeypatch, **overrides):
    values = {**VALID_PROVENANCE, **overrides}
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


@pytest.mark.asyncio
async def test_provenance_requires_authentication(api):
    response = await api.get("/api/v1/provenance")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.CLEANER, UserRole.TECHNICIAN])
async def test_provenance_denies_field_roles(api, db_session, tenant_a, role):
    user = await insert_user(db_session, tenant=tenant_a, role=role)
    response = await api.get("/api/v1/provenance", headers=auth_header(api, user))
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.TENANT_OWNER, UserRole.PROPERTY_MANAGER])
async def test_provenance_allows_owner_and_manager(
    api, db_session, tenant_a, monkeypatch, role
):
    set_provenance(monkeypatch)
    user = await insert_user(db_session, tenant=tenant_a, role=role)
    response = await api.get("/api/v1/provenance", headers=auth_header(api, user))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["provenance"] == {
        "repository_url": "https://github.com/example/project",
        "pull_request_number": 123,
        "commit_sha": "a" * 40,
        "actions_run_id": 456,
    }


@pytest.mark.asyncio
async def test_incomplete_provenance_is_unknown_without_partial_private_values(
    api, db_session, tenant_a, monkeypatch
):
    set_provenance(monkeypatch, app_provenance_actions_run_id="")
    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.PROPERTY_MANAGER)
    response = await api.get("/api/v1/provenance", headers=auth_header(api, user))
    body = response.json()
    assert response.status_code == 200
    assert body["provenance"] is None
    assert body["app_version"]
    assert all(field not in body for field in VALID_PROVENANCE)
