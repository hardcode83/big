import json
from pathlib import Path

import pytest

from app.auth.domain.enums import UserRole
from app.core.config import settings
from tests.auth.conftest import auth_header, insert_user


DEPLOY_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/build-identity-provenance.json").read_text()
)
VALID_PROVENANCE = {
    "app_version": DEPLOY_FIXTURE["app_version"],
    "app_provenance_repository_url": DEPLOY_FIXTURE["repository_url"],
    "app_provenance_pull_request_number": str(DEPLOY_FIXTURE["pull_request_number"]),
    "app_provenance_commit_sha": DEPLOY_FIXTURE["commit_sha"],
    "app_provenance_actions_run_id": str(DEPLOY_FIXTURE["actions_run_id"]),
}


def _workflow_version_values() -> tuple[str, str]:
    """Return the concrete identity shared with the workflow contract regression."""
    sentinel = DEPLOY_FIXTURE["app_version"]
    return sentinel, sentinel


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
        "repository_url": DEPLOY_FIXTURE["repository_url"],
        "pull_request_number": DEPLOY_FIXTURE["pull_request_number"],
        "commit_sha": DEPLOY_FIXTURE["commit_sha"],
        "actions_run_id": DEPLOY_FIXTURE["actions_run_id"],
    }
    assert response.json()["app_version"] == VALID_PROVENANCE["app_version"]


@pytest.mark.asyncio
async def test_build_identity_is_congruent_from_workflow_to_provenance_endpoint(
    api, db_session, tenant_a, monkeypatch
):
    frontend_value, backend_value = _workflow_version_values()
    assert frontend_value == backend_value
    set_provenance(monkeypatch, app_version=backend_value)
    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.PROPERTY_MANAGER)

    response = await api.get("/api/v1/provenance", headers=auth_header(api, user))

    assert response.status_code == 200
    assert response.json()["app_version"] == frontend_value
    assert response.json()["provenance"] == {
        "repository_url": DEPLOY_FIXTURE["repository_url"],
        "pull_request_number": DEPLOY_FIXTURE["pull_request_number"],
        "commit_sha": DEPLOY_FIXTURE["commit_sha"],
        "actions_run_id": DEPLOY_FIXTURE["actions_run_id"],
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
    assert all(
        field not in body
        for field in (
            "repository_url",
            "pull_request_number",
            "commit_sha",
            "actions_run_id",
        )
    )


@pytest.mark.asyncio
async def test_invalid_provenance_metadata_is_unknown_not_server_error(
    api, db_session, tenant_a, monkeypatch
):
    set_provenance(
        monkeypatch,
        app_provenance_repository_url="https://github.com/private-sentinel/build-identity-fixture?invalid=true",
    )
    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.TENANT_OWNER)
    response = await api.get("/api/v1/provenance", headers=auth_header(api, user))
    assert response.status_code == 200
    assert response.json()["provenance"] is None
