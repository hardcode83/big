"""Atomic validation of private build provenance (app-version-provenance D3)."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from app.core.config import Settings


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

        parsed = urlsplit(repository_url)
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or len(path_parts) != 2
            or parsed.query
            or parsed.fragment
        ):
            return None
        if not pull_request_number.isdecimal() or int(pull_request_number) <= 0:
            return None
        if len(commit_sha) != 40 or any(char not in "0123456789abcdef" for char in commit_sha):
            return None
        if not actions_run_id.isdecimal() or int(actions_run_id) <= 0:
            return None

        return cls(
            repository_url=repository_url.rstrip("/"),
            pull_request_number=int(pull_request_number),
            commit_sha=commit_sha,
            actions_run_id=int(actions_run_id),
        )
