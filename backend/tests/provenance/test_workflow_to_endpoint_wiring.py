"""Executable evidence for the complete deploy provenance wiring.

This test deliberately reads the production workflow instead of modelling it in
Python.  The shared fixture is only the concrete test deploy identity: workflow
expressions select its fields, and the resulting values are applied to the real
application before making a real authenticated ASGI HTTP request.
"""

import json
import os
import re
from pathlib import Path

import pytest

from app.auth.domain.enums import UserRole
from tests.auth.conftest import auth_header, insert_user
from tests.auth.test_provenance_authorization import set_provenance


FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/build-identity-provenance.json").read_text()
)
OUTPUT_FIELDS = (
    "version",
    "commit_short",
    "built_at",
    "repository_url",
    "pull_request_number",
    "commit_sha",
    "actions_run_id",
)
PRIVATE_ENV_TO_OUTPUT = {
    "APP_PROVENANCE_REPOSITORY_URL": "repository_url",
    "APP_PROVENANCE_PULL_REQUEST_NUMBER": "pull_request_number",
    "APP_PROVENANCE_COMMIT_SHA": "commit_sha",
    "APP_PROVENANCE_ACTIONS_RUN_ID": "actions_run_id",
}


def _workflow_path() -> Path:
    configured = os.environ.get("PROVENANCE_WORKFLOW_PATH")
    candidates = ([Path(configured)] if configured else []) + [
        Path("/workspace/deploy-dev.yml"),
        Path(__file__).parents[3] / ".github/workflows/deploy-dev.yml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.fail("the real deploy-dev workflow is not available to the wiring harness")


def _job_block(workflow: str, name: str) -> str:
    jobs_start = workflow.index("jobs:\n") + len("jobs:\n")
    jobs = workflow[jobs_start:]
    matches = list(re.finditer(r"^  ([a-z0-9-]+):\n", jobs, re.MULTILINE))
    for index, match in enumerate(matches):
        if match.group(1) == name:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(jobs)
            return jobs[match.start() : end]
    pytest.fail(f"real workflow is missing job {name}")


def _needs(job: str) -> set[str]:
    match = re.search(r"^    needs:\s*(.+)$", job, re.MULTILINE)
    if not match:
        return set()
    return set(re.findall(r"[a-z0-9-]+", match.group(1)))


def _output_declarations(provenance: str) -> dict[str, str]:
    return dict(
        re.findall(
            r"^      ([a-z_]+): \$\{\{ steps\.compose\.outputs\.([a-z_]+) \}\}$",
            provenance,
            re.MULTILINE,
        )
    )


def _consumer_output(job: str, variable: str) -> str:
    match = re.search(
        rf"{re.escape(variable)}=\$\{{\{{\s*needs\.provenance\.outputs\.([a-z_]+)\s*\}}\}}",
        job,
    )
    if not match:
        pytest.fail(f"{variable} no longer consumes a provenance output")
    return match.group(1)


def _fixture_value(output: str):
    if output == "version":
        return FIXTURE["app_version"]
    return FIXTURE[output]


@pytest.mark.asyncio
async def test_real_workflow_outputs_reach_authorized_provenance_endpoint(
    api, db_session, tenant_a, monkeypatch
):
    """Guard the complete workflow -> config -> HTTP response chain."""
    workflow = _workflow_path().read_text()
    provenance = _job_block(workflow, "provenance")
    frontend = _job_block(workflow, "build-frontend")
    deploy = _job_block(workflow, "deploy")

    declared = _output_declarations(provenance)
    assert declared == {field: field for field in OUTPUT_FIELDS}
    assert "node frontend/scripts/build-identity.mjs" in provenance
    assert "provenance" in _needs(frontend)
    assert "provenance" in _needs(deploy)

    frontend_version_output = _consumer_output(frontend, "NEXT_PUBLIC_APP_VERSION")
    backend_version_output = _consumer_output(deploy, 'echo "APP_VERSION')
    assert frontend_version_output == backend_version_output == "version"

    mapped = {
        "APP_VERSION": _fixture_value(backend_version_output),
        **{
            env_name: _fixture_value(_consumer_output(deploy, env_name))
            for env_name in PRIVATE_ENV_TO_OUTPUT
        },
    }
    assert {
        env_name: _consumer_output(deploy, env_name)
        for env_name in PRIVATE_ENV_TO_OUTPUT
    } == PRIVATE_ENV_TO_OUTPUT
    assert mapped["APP_VERSION"] == FIXTURE["app_version"]

    # These are the values the real deploy mapping gives the backend.  No test
    # literal is introduced here: every value comes from the workflow expression
    # and the one shared fixture above.
    set_provenance(
        monkeypatch,
        app_version=mapped["APP_VERSION"],
        app_provenance_repository_url=mapped["APP_PROVENANCE_REPOSITORY_URL"],
        app_provenance_pull_request_number=str(mapped["APP_PROVENANCE_PULL_REQUEST_NUMBER"]),
        app_provenance_commit_sha=mapped["APP_PROVENANCE_COMMIT_SHA"],
        app_provenance_actions_run_id=str(mapped["APP_PROVENANCE_ACTIONS_RUN_ID"]),
    )
    user = await insert_user(db_session, tenant=tenant_a, role=UserRole.PROPERTY_MANAGER)
    response = await api.get("/api/v1/provenance", headers=auth_header(api, user))

    assert response.status_code == 200
    body = response.json()
    assert body["app_version"] == FIXTURE["app_version"]
    assert body["provenance"] == {
        "repository_url": FIXTURE["repository_url"],
        "pull_request_number": FIXTURE["pull_request_number"],
        "commit_sha": FIXTURE["commit_sha"],
        "actions_run_id": FIXTURE["actions_run_id"],
    }
