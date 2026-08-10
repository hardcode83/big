import pytest
from pydantic import ValidationError

from app.provenance.api.schemas import PrivateProvenanceResponse


VALID = {
    "repository_url": "https://github.com/example/project",
    "pull_request_number": 1,
    "commit_sha": "a" * 40,
    "actions_run_id": 1,
}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository_url", "http://github.com/example/project"),
        ("repository_url", "https://gitlab.com/example/project"),
        ("pull_request_number", 0),
        ("pull_request_number", -1),
        ("commit_sha", "A" * 40),
        ("commit_sha", "a" * 39),
        ("actions_run_id", 0),
        ("actions_run_id", -1),
    ],
)
def test_private_schema_rejects_invalid_contract_values(field, value) -> None:
    with pytest.raises(ValidationError):
        PrivateProvenanceResponse.model_validate({**VALID, field: value})


def test_private_schema_requires_the_complete_atomic_block() -> None:
    for field in VALID:
        partial = {key: value for key, value in VALID.items() if key != field}
        with pytest.raises(ValidationError):
            PrivateProvenanceResponse.model_validate(partial)
