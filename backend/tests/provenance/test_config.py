import pytest

from app.core.config import Settings
from app.provenance.application.provenance import PrivateProvenance


_REQUIRED = {
    "jwt_secret_key": "0" * 64,
    "encryption_key": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
}


def _settings(**overrides: str) -> Settings:
    values = {
        **_REQUIRED,
        "app_provenance_repository_url": "https://github.com/autohostai-labs/AutoHostAI",
        "app_provenance_pull_request_number": "42",
        "app_provenance_commit_sha": "a" * 40,
        "app_provenance_actions_run_id": "123456",
        **overrides,
    }
    return Settings(_env_file=None, **values)


def test_private_provenance_is_atomic_when_all_fields_are_valid() -> None:
    value = PrivateProvenance.from_settings(_settings())

    assert value is not None
    assert value.pull_request_number == 42
    assert value.actions_run_id == 123456


def test_private_provenance_disappears_when_any_field_is_missing() -> None:
    for field in (
        "app_provenance_repository_url",
        "app_provenance_pull_request_number",
        "app_provenance_commit_sha",
        "app_provenance_actions_run_id",
    ):
        assert PrivateProvenance.from_settings(_settings(**{field: ""})) is None


def test_private_provenance_disappears_when_any_field_is_invalid() -> None:
    invalid = {
        "app_provenance_repository_url": "http://github.com/autohostai-labs/AutoHostAI",
        "app_provenance_pull_request_number": "issue-42",
        "app_provenance_commit_sha": "A" * 40,
        "app_provenance_actions_run_id": "0",
    }

    for field, value in invalid.items():
        assert PrivateProvenance.from_settings(_settings(**{field: value})) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com:443/autohostai-labs/AutoHostAI",
        "https://user@github.com/autohostai-labs/AutoHostAI",
        "https://github.com/autohostai-labs/AutoHostAI/",
        "https://github.com/autohostai-labs/AutoHostAI?query=private",
        "https://gitlab.com/autohostai-labs/AutoHostAI",
    ],
)
def test_repository_url_uses_canonical_contract_and_fails_closed(url: str) -> None:
    assert PrivateProvenance.from_settings(
        _settings(app_provenance_repository_url=url)
    ) is None
