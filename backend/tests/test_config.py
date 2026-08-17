import base64

import pytest
from pydantic import ValidationError

from app.core.config import (
    FERNET_KEY_BYTES,
    JWT_ALGORITHM,
    ConfigurationError,
    Settings,
    _load_settings,
)

# base64url of 32 bytes — the only shape Fernet accepts. Built rather than pasted so the
# relationship to FERNET_KEY_BYTES stays visible if that constant ever changes.
_VALID_FERNET_KEY = base64.urlsafe_b64encode(b"0" * FERNET_KEY_BYTES).decode()

_REQUIRED = {"jwt_secret_key": "0" * 64, "encryption_key": _VALID_FERNET_KEY}


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
    #
    # A valid encryption_key is passed explicitly so the failure can only come from the
    # signing key: without it this would raise for the missing field instead and pass for
    # the wrong reason.
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, jwt_secret_key=weak_key, encryption_key=_VALID_FERNET_KEY
        )


def test_settings_require_an_encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # R3.3. The compose stack injects ENCRYPTION_KEY into the container, so the absence
    # has to be simulated explicitly, exactly as for the signing key above.
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, jwt_secret_key="0" * 64)

    assert "encryption_key" in str(excinfo.value)


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "not-base64!!",
        # Right alphabet, wrong length — 31 and 33 bytes both decode cleanly.
        base64.urlsafe_b64encode(b"0" * 31).decode(),
        base64.urlsafe_b64encode(b"0" * 33).decode(),
        # What `openssl rand -hex 32` produces: 64 characters, and the shape a reader
        # would copy from the JWT key by analogy. It is the mistake worth pinning — it is
        # valid base64 and decodes cleanly, to 48 bytes, so only the length check catches it.
        "0" * 64,
    ],
)
def test_settings_reject_a_key_that_is_not_base64url_of_32_bytes(bad_key: str) -> None:
    # Checked at startup rather than at first use: a malformed key that only failed inside
    # `Fernet(...)` would surface as a runtime error on the sync path, long after deploy.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret_key="0" * 64, encryption_key=bad_key)


def test_a_standard_base64_key_is_accepted_because_fernet_accepts_it_too() -> None:
    # Measured, and it corrects an assumption worth recording: `urlsafe_b64decode` translates
    # `-_` to `+/` and then calls the permissive `b64decode`, so a key in the STANDARD base64
    # alphabet decodes fine — and `Fernet.__init__` uses that very same decoder, so it accepts
    # such a key as well. The `tr '+/' '-_'` in the Makefile therefore produces the canonical
    # url-safe form; it is not what makes the key valid.
    #
    # Pinned as a passing case rather than left untested because the first draft of this suite
    # asserted the opposite, and a validator made stricter than Fernet would reject keys that
    # work — including one already provisioned by Terraform.
    standard_alphabet = base64.b64encode(b"\xfb" * FERNET_KEY_BYTES).decode()
    assert "+" in standard_alphabet or "/" in standard_alphabet

    settings = Settings(
        _env_file=None, jwt_secret_key="0" * 64, encryption_key=standard_alphabet
    )

    assert settings.encryption_key == standard_alphabet


def test_the_boot_path_names_the_variable_without_printing_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # R3.4: "fallar rápido nombrando la variable y no SHALL imprimir su valor".
    #
    # `Settings(...)` on its own cannot satisfy this: Pydantic embeds the submitted input in
    # `ValidationError`, and for an `mode="after"` validator that input is the whole dict. So
    # the requirement is met at the boot path — `_load_settings`, which is what builds the
    # module-level singleton every entry point and `alembic/env.py` import.
    #
    # The distinction matters where it bites: in CI the key is generated and disposable, but
    # the deployed containers get the real Terraform-provisioned one, and a truncated value
    # would otherwise be printed by the error refusing it.
    secret = base64.urlsafe_b64encode(b"7" * (FERNET_KEY_BYTES - 1)).decode()
    monkeypatch.setenv("ENCRYPTION_KEY", secret)

    with pytest.raises(ConfigurationError) as excinfo:
        _load_settings()

    message = str(excinfo.value)
    assert "encryption_key" in message
    assert "base64url" in message
    assert secret not in message


def test_the_boot_path_does_not_leak_the_key_through_the_exception_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # What is load-bearing is that `ConfigurationError` is raised OUTSIDE the `except` block.
    # `raise ... from None` would NOT be enough and is deliberately not what the code does: it
    # only sets `__suppress_context__`, so `__context__` keeps referencing the original
    # `ValidationError` — hidden from the default traceback printer, still reachable by anything
    # that walks the chain. Asserting `__context__ is None` is what catches a refactor back to
    # raising inside the block.
    secret = base64.urlsafe_b64encode(b"7" * (FERNET_KEY_BYTES - 1)).decode()
    monkeypatch.setenv("ENCRYPTION_KEY", secret)

    with pytest.raises(ConfigurationError) as excinfo:
        _load_settings()

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_the_boot_path_also_withholds_the_signing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Not a requirement of this change, but the same code path and the same leak: the JWT key
    # had this exposure before and the wrapper closes it too. Pinned so a later refactor that
    # narrowed the sanitising to one field would be caught.
    monkeypatch.setenv("JWT_SECRET_KEY", "too-short-but-still-a-secret")

    with pytest.raises(ConfigurationError) as excinfo:
        _load_settings()

    message = str(excinfo.value)
    assert "jwt_secret_key" in message
    assert "too-short-but-still-a-secret" not in message


def test_the_encryption_key_error_names_the_variable_and_the_expected_shape() -> None:
    # A message that identifies the variable and says what shape is expected, so a broken
    # deploy is diagnosable from the log alone.
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            _env_file=None, jwt_secret_key="0" * 64, encryption_key="not-a-fernet-key"
        )

    message = str(excinfo.value)
    assert "encryption_key" in message
    assert "base64url" in message


def test_one_bad_field_does_not_dump_every_other_secret() -> None:
    # This is why both secret checks are `field_validator` and not `model_validator`. A
    # model-level validator reports the WHOLE input dict as the offending value, so a single
    # invalid field printed every other secret alongside it — measured on this branch before
    # the fix: an invalid encryption key dumped `postgres_password`, `channex_api_key` and the
    # bootstrap passwords, and a whitespace-padded signing key dumped a valid, live Fernet key.
    #
    # An earlier version of this file argued that leak was unavoidable and mitigated by the key
    # being disposable. Both halves were wrong: the fix is a field validator, and the key is
    # NOT disposable — Terraform provisions it once (`random_bytes.encryption_key`), stores it
    # in OCI Vault and the CD renders it into the VM's .env, while `app/core/crypto.py` records
    # that a changed key makes every stored ciphertext undecryptable.
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            _env_file=None,
            jwt_secret_key="0" * 64,
            encryption_key="not-a-fernet-key",
            postgres_password="pg-secret-value",
            channex_api_key="channex-secret-value",
            bootstrap_owner_password="owner-secret-value",
        )

    rendered = str(excinfo.value) + repr(excinfo.value.errors())
    for other_secret in (
        "pg-secret-value",
        "channex-secret-value",
        "owner-secret-value",
    ):
        assert other_secret not in rendered


def test_a_bad_signing_key_does_not_dump_the_encryption_key() -> None:
    # The reverse direction of the same leak, and the sharper one: the signing-key check
    # predates this change, so adding `encryption_key` as a field would have widened an
    # existing validator to print a VALID, live encryption key on an unrelated misconfiguration.
    live_key = base64.urlsafe_b64encode(b"\x2a" * FERNET_KEY_BYTES).decode()

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, jwt_secret_key=" " * 64, encryption_key=live_key)

    rendered = str(excinfo.value) + repr(excinfo.value.errors())
    assert live_key not in rendered


def test_a_key_with_surrounding_whitespace_is_accepted() -> None:
    # A key written into .env by a shell heredoc or copied from a console often carries a
    # trailing newline; rejecting it would be a confusing failure for a correct key.
    settings = Settings(
        _env_file=None,
        jwt_secret_key="0" * 64,
        encryption_key=f"  {_VALID_FERNET_KEY}\n",
    )

    assert settings.encryption_key.strip() == _VALID_FERNET_KEY


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


def test_password_recovery_has_its_documented_defaults() -> None:
    """Change `auth-account-recovery`, design D13."""
    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.password_reset_token_minutes == 30
    assert settings.password_reset_max_live_tokens == 3
    assert settings.frontend_base_url == "http://localhost:3000"


@pytest.mark.parametrize(
    ("env_var", "field_name", "value"),
    [
        ("PASSWORD_RESET_TOKEN_MINUTES", "password_reset_token_minutes", 15),
        ("PASSWORD_RESET_MAX_LIVE_TOKENS", "password_reset_max_live_tokens", 5),
    ],
)
def test_password_recovery_is_configurable_per_environment(
    monkeypatch: pytest.MonkeyPatch, env_var: str, field_name: str, value: int
) -> None:
    # R3.4 says the token lifetime is configurable; asserting only the default would not
    # catch a refactor that hardcoded it.
    monkeypatch.setenv(env_var, str(value))

    assert getattr(Settings(_env_file=None, **_REQUIRED), field_name) == value


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        # R3.4 says the system SHALL *fijar* a short lifetime. Unbounded, "short" would be a
        # property of the default rather than of the system: 43200 minutes is 30 days.
        ("PASSWORD_RESET_TOKEN_MINUTES", "43200"),
        ("PASSWORD_RESET_TOKEN_MINUTES", "0"),
        ("PASSWORD_RESET_TOKEN_MINUTES", "-1"),
        # 0 or negative does not tighten D7's cap, it changes what it means — refusing every
        # recovery, or wrapping to unlimited, depending on how the comparison is written.
        ("PASSWORD_RESET_MAX_LIVE_TOKENS", "0"),
        ("PASSWORD_RESET_MAX_LIVE_TOKENS", "-3"),
        ("PASSWORD_RESET_MAX_LIVE_TOKENS", "1000"),
    ],
)
def test_a_recovery_setting_outside_its_bounds_is_refused(
    monkeypatch: pytest.MonkeyPatch, env_var: str, value: str
) -> None:
    monkeypatch.setenv(env_var, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **_REQUIRED)


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        # NOT 1: the grace period must be strictly shorter than the lifetime and its own
        # floor is 1, so 2 is the smallest coherent lifetime. Asserted below.
        ("PASSWORD_RESET_TOKEN_MINUTES", "720"),
        ("PASSWORD_RESET_MAX_LIVE_TOKENS", "1"),
        ("PASSWORD_RESET_MAX_LIVE_TOKENS", "10"),
        ("PASSWORD_RESET_GRACE_MINUTES", "1"),
        ("PASSWORD_RESET_GRACE_MINUTES", "29"),
    ],
)
def test_the_bounds_are_inclusive_at_their_edges(
    monkeypatch: pytest.MonkeyPatch, env_var: str, value: str
) -> None:
    """The bound must not make a legitimate tuning value unreachable."""
    monkeypatch.setenv(env_var, value)

    assert Settings(_env_file=None, **_REQUIRED)


def test_the_shortest_coherent_token_lifetime_is_two_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consequence of the grace coupling, stated rather than discovered.

    `PASSWORD_RESET_TOKEN_MINUTES=1` used to be accepted and is now impossible: the grace
    must be strictly shorter and its floor is 1. Pinned because an operator reading only the
    field bounds would expect 1 to work.
    """
    monkeypatch.setenv("PASSWORD_RESET_TOKEN_MINUTES", "2")
    monkeypatch.setenv("PASSWORD_RESET_GRACE_MINUTES", "1")

    assert Settings(_env_file=None, **_REQUIRED).password_reset_token_minutes == 2


@pytest.mark.parametrize(
    ("token_minutes", "grace_minutes"),
    [("30", "30"), ("30", "45"), ("2", "2"), ("1", "1")],
)
def test_a_grace_at_or_above_the_token_lifetime_is_refused(
    monkeypatch: pytest.MonkeyPatch, token_minutes: str, grace_minutes: str
) -> None:
    """R2.5 / design D7's grace amendment, as a coupling the suite refuses to let drift.

    A grace at or above the lifetime makes NOTHING old enough to retire, which silently turns
    the per-account cap back into a permanent discard — the suppression vector the amendment
    exists to close. Same shape as D4's coupling between the password minimum and the
    temporary-password generator: a relationship between two values, so neither field's own
    bounds can express it.
    """
    monkeypatch.setenv("PASSWORD_RESET_TOKEN_MINUTES", token_minutes)
    monkeypatch.setenv("PASSWORD_RESET_GRACE_MINUTES", grace_minutes)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **_REQUIRED)


def test_password_recovery_grace_has_its_documented_default() -> None:
    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.password_reset_grace_minutes == 2
    assert settings.password_reset_grace_minutes < settings.password_reset_token_minutes


def test_the_frontend_base_url_is_configurable_per_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.autohost.example")

    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.frontend_base_url == "https://app.autohost.example"


def test_there_is_no_password_minimum_length_setting() -> None:
    """Design D4, asserted as an absence.

    R1.6 obliges the policy to accept every password `generate_temporary_password()` emits,
    so a deployment that raised the minimum above `TEMPORARY_PASSWORD_LENGTH` would make the
    system reject the credentials it hands out itself. The minimum is a domain constant, and
    turning it into a setting must be a decision, not a drive-by.
    """
    assert not [name for name in Settings.model_fields if "password_min" in name]


def test_no_smtp_setting_is_declared_before_it_is_used() -> None:
    """Design D13 and rule 8 of `steering/security.md`, asserted as an absence.

    The six `SMTP_*` names are reserved by name and without value in `.env.example` for
    `hardening-release`. Rule 8 requires a secret IN USE to fail fast when it is missing;
    declaring these now would make the application demand credentials no code reads, which
    is how a fail-fast rule gets a reputation for crying wolf.
    """
    assert not [name for name in Settings.model_fields if name.startswith("smtp_")]


def test_notification_delivery_has_its_documented_defaults() -> None:
    """Change `access-notifications`, design D4."""
    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.notification_max_attempts == 3
    assert settings.notification_batch_size == 100


@pytest.mark.parametrize(
    ("env_var", "field_name", "value"),
    [
        ("NOTIFICATION_MAX_ATTEMPTS", "notification_max_attempts", 5),
        ("NOTIFICATION_BATCH_SIZE", "notification_batch_size", 25),
    ],
)
def test_notification_delivery_is_configurable_per_environment(
    monkeypatch: pytest.MonkeyPatch, env_var: str, field_name: str, value: int
) -> None:
    monkeypatch.setenv(env_var, str(value))

    assert getattr(Settings(_env_file=None, **_REQUIRED), field_name) == value


def test_there_is_no_notification_backoff_setting() -> None:
    """Design D4, asserted as an absence.

    `notification_logs` has no "next attempt at" column, so a backoff setting would promise
    pacing the schema cannot deliver. Adding one must come with the column and a decision,
    not slip in as a knob.
    """
    settings = Settings(_env_file=None, **_REQUIRED)

    assert not hasattr(settings, "notification_retry_backoff_seconds")


def test_the_application_has_no_setting_for_a_trusted_client_ip_header() -> None:
    """Change `api-ingress-routing`, design D3: resolving the real client address is
    uvicorn's job, gated by `--forwarded-allow-ips`. A setting here would be a second
    mechanism deciding whether to trust a peer the first one may already have
    rewritten. Asserted as an absence so re-adding it fails loudly instead of
    quietly reintroducing the overlap.
    """
    assert not hasattr(Settings(_env_file=None, **_REQUIRED), "trusted_client_ip_header")


def test_bootstrap_credentials_have_no_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # The absence of a DEFAULT is the property under test, so the ambient environment
    # has to be cleared: a developer with BOOTSTRAP_* filled in their own .env — which
    # `make bootstrap` requires — would otherwise fail this for the wrong reason.
    for name in ("BOOTSTRAP_OWNER_PASSWORD", "BOOTSTRAP_MANAGER_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.bootstrap_owner_password == ""
    assert settings.bootstrap_manager_password == ""


def test_seed_demo_credentials_have_no_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same reasoning as the BOOTSTRAP_* test above: the absence of a DEFAULT is the property
    # under test, and a developer who filled these in their own .env to run `make seed-demo`
    # would otherwise pass this for the wrong reason.
    for name in ("SEED_CLEANER_PASSWORD", "SEED_TECHNICIAN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.seed_cleaner_password == ""
    assert settings.seed_technician_password == ""


def test_the_boot_path_also_withholds_the_seed_demo_passwords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Design D4 claims these two stay inside the protection `_load_settings` already gives the
    # `bootstrap_*_password` fields. That claim is about the boot path, not about their names,
    # so it is asserted the way the sibling tests above assert theirs: make an unrelated field
    # fail and check the message carries no password.
    monkeypatch.setenv("JWT_SECRET_KEY", "too-short-but-still-a-secret")
    monkeypatch.setenv("SEED_CLEANER_PASSWORD", "cleaner-s3cr3t")
    monkeypatch.setenv("SEED_TECHNICIAN_PASSWORD", "technician-s3cr3t")

    with pytest.raises(ConfigurationError) as excinfo:
        _load_settings()

    message = str(excinfo.value)
    assert "cleaner-s3cr3t" not in message
    assert "technician-s3cr3t" not in message


def test_jwt_algorithm_is_a_constant_not_a_setting() -> None:
    assert JWT_ALGORITHM == "HS256"
    assert "jwt_algorithm" not in Settings.model_fields


# --- The guest portal (`guest-portal-api` R1.3, R2.4, design D3, D6) ------------------


def test_the_guest_portal_has_its_documented_defaults() -> None:
    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.guest_portal_token_grace_days == 2
    assert settings.guest_portal_rate_limit_per_minute == 60
    assert settings.guest_portal_probe_limit_per_minute == 20
    # `None`, and deliberately not a placeholder string (D9, R3.1): an installation that has
    # not chosen a support channel serves the field as `null` and the portal shows no help
    # card, which is honest. A default like "support@example.com" would be published to every
    # guest of every tenant that forgot to set it.
    assert settings.guest_portal_support_channel is None


@pytest.mark.parametrize(
    ("env_var", "field_name", "value"),
    [
        ("GUEST_PORTAL_TOKEN_GRACE_DAYS", "guest_portal_token_grace_days", 7),
        ("GUEST_PORTAL_RATE_LIMIT_PER_MINUTE", "guest_portal_rate_limit_per_minute", 5),
        ("GUEST_PORTAL_PROBE_LIMIT_PER_MINUTE", "guest_portal_probe_limit_per_minute", 3),
        ("GUEST_PORTAL_SUPPORT_CHANNEL", "guest_portal_support_channel", "+34 600 000 000"),
    ],
)
def test_the_guest_portal_is_configurable_per_environment(
    monkeypatch: pytest.MonkeyPatch, env_var: str, field_name: str, value: int | str
) -> None:
    monkeypatch.setenv(env_var, str(value))

    assert getattr(Settings(_env_file=None, **_REQUIRED), field_name) == value


def test_the_probe_limit_is_stricter_than_the_authorised_one_by_default() -> None:
    """D6: the two limits are asymmetric, and the direction is the design.

    Probing has to cost more than using the portal legitimately. Asserting the relation and
    not just the two numbers is what catches someone "harmonising" them later.
    """
    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.guest_portal_probe_limit_per_minute < settings.guest_portal_rate_limit_per_minute


def test_there_is_no_expiry_setting_for_a_guest_token() -> None:
    """D3, asserted as an absence.

    The window is derived from the stay at authorisation time — check-out plus the grace —
    so an absolute lifetime setting would be a second, contradictory answer to "when does
    this token stop working", and the one that goes stale when the booking moves.
    """
    settings = Settings(_env_file=None, **_REQUIRED)

    assert not hasattr(settings, "guest_portal_token_ttl_minutes")
    assert not hasattr(settings, "guest_portal_token_expiry_days")


# --- Object storage (`object-storage-provisioning` R2.1, R3.1, design D4) -------------


def test_the_object_store_settings_default_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """R3.1: the empty default is what makes merging this change inert.

    Cleared from the ambient environment on purpose — the deployed `.env` fills all three, so
    a developer running the suite against a configured stack would otherwise pass this for the
    wrong reason.
    """
    for name in ("S3_BUCKET", "S3_REGION", "S3_ENDPOINT_URL"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None, **_REQUIRED)

    assert settings.s3_bucket == ""
    assert settings.s3_region == ""
    assert settings.s3_endpoint_url == ""


@pytest.mark.parametrize(
    ("env_var", "field_name", "value"),
    [
        ("S3_BUCKET", "s3_bucket", "autohostai-dev-media"),
        ("S3_REGION", "s3_region", "eu-frankfurt-1"),
        (
            "S3_ENDPOINT_URL",
            "s3_endpoint_url",
            "https://ns.compat.objectstorage.eu-frankfurt-1.oraclecloud.com",
        ),
    ],
)
def test_the_object_store_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, env_var: str, field_name: str, value: str
) -> None:
    monkeypatch.setenv(env_var, value)

    assert getattr(Settings(_env_file=None, **_REQUIRED), field_name) == value


def test_the_object_store_credentials_are_not_settings() -> None:
    """R2.1 / design D4, asserted as an absence.

    The access key pair travels by boto3's standard chain. Reading it into `Settings` would put
    a live credential inside an object that any debug `repr` prints, so re-adding it has to
    fail here rather than be noticed in a log.
    """
    assert "aws_access_key_id" not in Settings.model_fields
    assert "aws_secret_access_key" not in Settings.model_fields
    assert "s3_access_key_id" not in Settings.model_fields
    assert "s3_secret_access_key" not in Settings.model_fields
