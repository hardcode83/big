import pytest
from pydantic import ValidationError

from app.core.config import JWT_ALGORITHM, Settings

_REQUIRED = {"jwt_secret_key": "0" * 64}


def test_settings_require_a_jwt_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # The compose stack injects JWT_SECRET_KEY into the container, so the absence
    # has to be simulated explicitly.
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    assert "jwt_secret_key" in str(excinfo.value)


@pytest.mark.parametrize("weak_key", ["", "x", "changeme", " " * 64, "  short  "])
def test_settings_reject_a_weak_jwt_signing_key(weak_key: str) -> None:
    # A placeholder key is as good as no key: it is brute-forceable offline from
    # any issued token, which is exactly what R1.7 exists to prevent.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret_key=weak_key)


def test_token_lifetimes_and_throttle_have_prd_defaults() -> None:
    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.jwt_access_token_minutes == 15
    assert settings.jwt_refresh_token_days == 7
    assert settings.login_rate_limit_per_minute == 10
    assert settings.login_max_failed_attempts == 10
    assert settings.login_lockout_minutes == 15


@pytest.mark.parametrize(
    ("env_var", "field_name", "value"),
    [
        ("JWT_ACCESS_TOKEN_MINUTES", "jwt_access_token_minutes", 42),
        ("JWT_REFRESH_TOKEN_DAYS", "jwt_refresh_token_days", 3),
        ("LOGIN_RATE_LIMIT_PER_MINUTE", "login_rate_limit_per_minute", 4),
        ("LOGIN_MAX_FAILED_ATTEMPTS", "login_max_failed_attempts", 5),
        ("LOGIN_LOCKOUT_MINUTES", "login_lockout_minutes", 30),
    ],
)
def test_lifetimes_and_throttle_are_configurable_per_environment(
    monkeypatch: pytest.MonkeyPatch, env_var: str, field_name: str, value: int
) -> None:
    # R1.6 says "ambas configurables por entorno" — asserting only the defaults
    # would not catch a refactor that hardcoded them.
    monkeypatch.setenv(env_var, str(value))

    assert getattr(Settings(_env_file=None, **_REQUIRED), field_name) == value


def test_no_client_ip_header_is_trusted_by_default() -> None:
    assert Settings(_env_file=None, **_REQUIRED).trusted_client_ip_header == ""


def test_bootstrap_credentials_have_no_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # The absence of a DEFAULT is the property under test, so the ambient environment
    # has to be cleared: a developer with BOOTSTRAP_* filled in their own .env — which
    # `make bootstrap` requires — would otherwise fail this for the wrong reason.
    for name in ("BOOTSTRAP_OWNER_PASSWORD", "BOOTSTRAP_MANAGER_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.bootstrap_owner_password == ""
    assert settings.bootstrap_manager_password == ""


def test_jwt_algorithm_is_a_constant_not_a_setting() -> None:
    assert JWT_ALGORITHM == "HS256"
    assert "jwt_algorithm" not in Settings.model_fields
