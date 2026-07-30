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


_BUILD_IDENTITY_ENV = (
    "APP_VERSION",
    "BUILD_COMMIT",
    "BUILD_PR",
    "BUILT_AT",
    "BUILD_RUN_ID",
    "BUILD_REF",
)


def test_build_identity_is_optional_so_an_unbaked_image_still_boots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The whole point of R2.10/design D4: `settings = Settings()` runs at import time,
    # so a required build-identity field would stop an image built without build-args
    # from serving anything at all. Knowing the version must never block booting.
    for name in _BUILD_IDENTITY_ENV:
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.app_version == ""
    assert settings.build_commit == ""
    assert settings.build_pr is None
    assert settings.built_at == ""
    assert settings.build_run_id == ""
    assert settings.build_ref == ""


@pytest.mark.parametrize(
    "unusable",
    [
        "",  # direct push to main, no PR — the Dockerfile still defines the variable
        "   ",
        "\t",
        "unknown",  # one of the two renderings R2.6 explicitly sanctions
        "#42",  # the '#' not stripped by whoever composed the build-arg
        "42a",
        "1.2",
        "-42",
        "0",  # PR numbers start at 1, so 0 means "no PR", not PR zero
        "null",
        "²",  # `str.isdigit()` is True here but `int()` raises — the gap the panel found
        "₁",
    ],
)
def test_an_unusable_build_pr_becomes_none_instead_of_killing_the_image(
    monkeypatch: pytest.MonkeyPatch, unusable: str
) -> None:
    # The coercion has to be TOTAL, not just for blank strings: `settings = Settings()`
    # runs at import time, so ANY value this field cannot parse means the image does not
    # boot at all. R2.10 — "la versión nunca debe poder impedir el arranque" — makes
    # losing the deployment over a metadata field the one outcome that is not acceptable.
    # The extraction pattern lives in deploy-dev.yml, outside this module, so nothing
    # here can assume only digits or blanks arrive.
    monkeypatch.setenv("BUILD_PR", unusable)

    assert Settings(_env_file=None, **_REQUIRED).build_pr is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("42", 42),
        (" 42 ", 42),
        ("7", 7),
        ("007", 7),
        # Nd-category digits DO parse with int(), unlike the No-category "²" above. Kept
        # as a value rather than an error for the same reason as everything else here:
        # nothing about this field is worth refusing to boot over.
        ("٤٢", 42),
    ],
)
def test_a_well_formed_build_pr_is_still_parsed(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: int
) -> None:
    # The total coercion must not swallow the happy path into None.
    monkeypatch.setenv("BUILD_PR", raw)

    assert Settings(_env_file=None, **_REQUIRED).build_pr == expected


def test_build_identity_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Asserting only the defaults would not catch a refactor that stopped reading the
    # baked ENV, which is the single source the endpoint reports from.
    monkeypatch.setenv("APP_VERSION", "0.1.0+2026-07-30.a2f3c1d")
    monkeypatch.setenv("BUILD_COMMIT", "a2f3c1d3f9b2000000000000000000000000000f")
    monkeypatch.setenv("BUILD_PR", "42")
    monkeypatch.setenv("BUILT_AT", "2026-07-30T09:14:02Z")
    monkeypatch.setenv("BUILD_RUN_ID", "1234567890")
    monkeypatch.setenv("BUILD_REF", "main")

    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.app_version == "0.1.0+2026-07-30.a2f3c1d"
    assert settings.build_commit == "a2f3c1d3f9b2000000000000000000000000000f"
    assert settings.build_pr == 42
    assert settings.built_at == "2026-07-30T09:14:02Z"
    assert settings.build_run_id == "1234567890"
    assert settings.build_ref == "main"


def test_jwt_algorithm_is_a_constant_not_a_setting() -> None:
    assert JWT_ALGORITHM == "HS256"
    assert "jwt_algorithm" not in Settings.model_fields
