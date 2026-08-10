from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


RepositoryUrl = Annotated[
    str,
    StringConstraints(pattern=r"^https://github\.com/[^/\s]+/[^/\s]+$"),
]
CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class PrivateProvenanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_url: RepositoryUrl = Field(
        description="HTTPS URL of the GitHub repository that produced the build."
    )
    pull_request_number: int = Field(
        ge=1, description="Positive Pull Request number."
    )
    commit_sha: CommitSha = Field(
        description="The complete 40-character lowercase hexadecimal commit SHA."
    )
    actions_run_id: int = Field(
        ge=1, description="Positive GitHub Actions run ID."
    )


class BuildProvenanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_version: str
    provenance: PrivateProvenanceResponse | None
