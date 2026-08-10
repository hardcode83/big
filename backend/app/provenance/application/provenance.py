"""Atomic validation of private build provenance (app-version-provenance D3)."""

from dataclasses import dataclass

from app.core.config import Settings
from app.provenance.contract import validate_contract_values


@dataclass(frozen=True)
class PrivateProvenance:
    repository_url: str
    pull_request_number: int
    commit_sha: str
    actions_run_id: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "PrivateProvenance | None":
        repository_url = settings.app_provenance_repository_url.strip()
        pull_request_number = settings.app_provenance_pull_request_number.strip()
        commit_sha = settings.app_provenance_commit_sha.strip()
        actions_run_id = settings.app_provenance_actions_run_id.strip()

        if not repository_url or not pull_request_number or not commit_sha or not actions_run_id:
            return None

        values = {
            "APP_PROVENANCE_REPOSITORY_URL": repository_url,
            "APP_PROVENANCE_PULL_REQUEST_NUMBER": pull_request_number,
            "APP_PROVENANCE_COMMIT_SHA": commit_sha,
            "APP_PROVENANCE_ACTIONS_RUN_ID": actions_run_id,
        }
        if validate_contract_values(values):
            return None

        return cls(
            repository_url=repository_url,
            pull_request_number=int(pull_request_number),
            commit_sha=commit_sha,
            actions_run_id=int(actions_run_id),
        )
