import base64
import binascii
from pathlib import Path

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# A Fernet key is base64url of exactly this many bytes (16 for signing + 16 for AES).
FERNET_KEY_BYTES = 32

# Deliberately NOT configurable (design D3): a deployment that set this to "none"
# would disable signature verification altogether.
JWT_ALGORITHM = "HS256"


class Settings(BaseSettings):
    # `validate_default=True` restores a property the move to field validators would otherwise
    # have dropped: a `field_validator` does not run on a default value, while the
    # `model_validator(mode="after")` it replaced did. Unreachable today — `jwt_secret_key` and
    # `encryption_key` are both required and rule 8 forbids giving them one — but the day someone
    # adds a default "just for tests", it would ship unvalidated. Cheap insurance, and no other
    # field pairs a default with a validator, so nothing else changes behaviour.
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT_ENV_FILE, extra="ignore", validate_default=True
    )

    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    redis_url: str = "redis://redis:6379/0"
    database_url: str = ""

    # Required: the application must refuse to boot without a signing key (R1.7)
    # rather than serve with a default one. The 32-character floor matches the
    # 256-bit key HS256 expects — a placeholder like "changeme" would be
    # brute-forceable offline from any issued token, which is the same failure
    # R1.7 exists to prevent. `make up` generates 64 hex characters.
    jwt_secret_key: str = Field(min_length=32)
    jwt_access_token_minutes: int = 15
    jwt_refresh_token_days: int = 7

    # Fernet key for secrets at rest (rule 3 of steering/security.md, R3.3). Required
    # for the same reason as the signing key above: a default would mean shipping a
    # publicly known key, and "encrypted with a key everyone has" is worse than
    # cleartext because it reads as protected.
    #
    # Terraform already generates this value and the CD writes it into the VM's .env
    # (`infra/environments/dev/main.tf`, `encryption_key_fernet`); R3.3 forbids adding
    # a second key or a second variable name, so this field consumes that one.
    #
    # NOT `openssl rand -hex 32` like the JWT key: Fernet expects base64url of 32
    # bytes, and hex would be rejected at construction time. `make up` generates it.
    encryption_key: str

    bcrypt_rounds: int = 12
    # How many password hashes may run at once (design D21). bcrypt is CPU-bound and
    # runs in a worker thread, so this is the login endpoint's CPU budget: too low
    # queues legitimate logins, too high lets one burst of failed attempts starve
    # every other request on the box. `None` derives it from the visible CPU count,
    # which is the only value that adapts to the 4-OCPU dev VM and to a laptop alike.
    bcrypt_max_concurrency: int | None = None

    login_rate_limit_per_minute: int = 10
    login_max_failed_attempts: int = 10
    login_lockout_minutes: int = 15

    # No setting for the real-client-IP header, deliberately (change
    # `api-ingress-routing`, design D3). Resolving it is uvicorn's job:
    # `ProxyHeadersMiddleware` rewrites `scope["client"]` from `X-Forwarded-For`, but
    # only for peers listed in `--forwarded-allow-ips`, which the deploy compose sets
    # to the frontend container's static address. A second reader in the application
    # would have to decide whether to trust a peer the first one may already have
    # rewritten — a check validating its own input.

    # Limits of the CSV reservation import (R4.3, design D11). Both are checked BEFORE
    # parsing: a 200 MB upload must be refused, not streamed into memory first. The byte
    # ceiling is rule 6 of `steering/security.md` ("tamaño máx. configurable, default 10 MB");
    # the row ceiling is this change's, because a small file can still hold a million rows.
    csv_import_max_bytes: int = 10 * 1024 * 1024
    csv_import_max_rows: int = 1000

    # The ceiling for every OTHER body under `/api/v1/` (change `api-ingress-routing`). It is
    # deliberately separate from `csv_import_max_bytes` and two orders of magnitude smaller:
    # these are JSON payloads, and the largest legitimate one in the contract is a reservation.
    # It exists because `/api/v1` is now reachable from the internet, where an unbounded body on
    # an anonymous endpoint is a memory amplifier — measured at 1 GiB of RSS from a single 400 MB
    # POST to `/auth/login`, read by FastAPI before the login throttle runs. 1 MiB leaves roughly
    # three orders of magnitude of headroom over a real request.
    request_max_bytes: int = 1024 * 1024

    # Build provenance is private backend configuration. These remain strings so an absent
    # value in the deploy `.env` is an unavailable provenance block, not a boot-time failure;
    # `PrivateProvenance.from_settings` validates the four values atomically before exposure.
    app_provenance_repository_url: str = ""
    app_provenance_pull_request_number: str = ""
    app_provenance_commit_sha: str = ""
    app_provenance_actions_run_id: str = ""

    # Channex staging (change `channex-staging-adapter`, design D3/D4). Only
    # `cli/pms_sync.py --provider channex` reads these; the application never does.
    #
    # The key has NO default: rule 8 of steering/security.md, and R3.2 requires the
    # command to abort naming the missing variable instead of falling back to the mock.
    channex_api_key: str = ""
    # Defaults to STAGING on purpose: this adapter is a dev/validation tool (ADR 0006 keeps
    # Beds24 as the MVP provider), so a misconfiguration must land on staging and never on
    # a production Channex account that could be talking to real OTA listings.
    channex_base_url: str = "https://staging.channex.io/api/v1"
    # Channex pages with a default `limit` of 10, so a sync MUST paginate. The cap exists
    # so a provider bug reporting an ever-growing `total` cannot spin forever; reaching it
    # raises rather than truncating (design D6) — silently returning a short list inside a
    # sync is indistinguishable from "the PMS had nothing more".
    channex_max_pages: int = 50
    channex_page_limit: int = 100
    channex_timeout_seconds: float = 30.0

    # Beds24 (change `pms-beds24-adapter`, design D2). **No credential here, deliberately.**
    # Beds24's refresh token is an ACCOUNT credential stored encrypted in `pms_credentials` and
    # governed by rule 3 of steering/security.md; `BEDS24_REFRESH_TOKEN` exists only for the
    # measurement bench in `scripts/`, which rule 8 covers. Two homes for one credential is how
    # one of them stops being rotated.
    #
    # No `beds24_base_url` either: the base URL and the host allowlist are constants in
    # `infrastructure/beds24/client.py`. Channex has one because its default points at staging,
    # which is what stops a mistake reaching a live account — Beds24 has **no staging
    # environment**, so a configurable base would be a lever with no use case, guarding a
    # credential that grants write access to every property of the account.
    beds24_max_pages: int = 50
    beds24_page_limit: int = 100
    beds24_timeout_seconds: float = 30.0

    bootstrap_tenant_name: str = ""
    bootstrap_tenant_billing_email: str = ""
    bootstrap_owner_name: str = ""
    bootstrap_owner_email: str = ""
    bootstrap_owner_password: str = ""
    bootstrap_manager_name: str = ""
    bootstrap_manager_email: str = ""
    bootstrap_manager_password: str = ""

    # Both secret checks are FIELD validators, not model validators, and that is a security
    # property rather than a style choice. A `model_validator(mode="after")` reports the whole
    # settings input as the offending value, so any one failure printed every other secret in
    # the dict: a whitespace-padded signing key dumped a valid, live `encryption_key`, and an
    # invalid encryption key dumped `POSTGRES_PASSWORD`, `CHANNEX_API_KEY` and the bootstrap
    # passwords. A field validator scopes that value to its own field.
    #
    # `_default_database_url` below stays a model validator because it genuinely needs several
    # fields — it is safe there only because it cannot raise.
    @field_validator("jwt_secret_key")
    @classmethod
    def _reject_whitespace_jwt_secret(cls, value: str) -> str:
        if len(value.strip()) < 32:
            raise ValueError(
                "jwt_secret_key must have at least 32 non-whitespace characters"
            )
        return value

    @field_validator("encryption_key")
    @classmethod
    def _reject_invalid_encryption_key(cls, value: str) -> str:
        # Checked here rather than with `Field(min_length=44)` because length is not the
        # property that matters: a 44-character string that is not base64url of 32 bytes
        # fails later, inside `Fernet(...)`, at the first attempt to read a credential —
        # which is a runtime failure on the sync path instead of a refusal to boot.
        #
        # Validated with the standard library on purpose, so `config.py` does not import
        # `cryptography`: this module is imported by `alembic/env.py` and by every entry
        # point, and the check needs no more than decoding 32 bytes.
        key = value.strip()
        try:
            raw = base64.urlsafe_b64decode(key)
        except (binascii.Error, ValueError) as error:
            raise ValueError(
                "encryption_key must be base64url-encoded 32 bytes "
                "(generate with: openssl rand 32 | base64 | tr '+/' '-_')"
            ) from error
        if len(raw) != FERNET_KEY_BYTES:
            # The shape is repeated here rather than only in the branch above because this is
            # the branch a hex key lands in: "0" * 64 is valid base64url and decodes cleanly
            # to 48 bytes, so the reader who copied `openssl rand -hex 32` from the signing
            # key sees this message and not the other one.
            raise ValueError(
                f"encryption_key must be base64url-encoded {FERNET_KEY_BYTES} bytes; "
                f"this value decodes to {len(raw)} "
                "(generate with: openssl rand 32 | base64 | tr '+/' '-_')"
            )
        return value

    @model_validator(mode="after")
    def _default_database_url(self) -> "Settings":
        # Docker Compose overrides this with the `postgres` hostname (see
        # docker-compose.yml); this default lets host-side commands
        # (`cd backend && uv run pytest`) reach Postgres via the published
        # port, since `postgres` doesn't resolve outside the compose network.
        if not self.database_url:
            self.database_url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@localhost:5432/{self.postgres_db}"
            )
        return self


class ConfigurationError(RuntimeError):
    """Settings could not be loaded, reported without echoing any submitted value.

    Exists because `ValidationError.__str__()` embeds the constructor input — the whole dict
    for an `mode="after"` validator — so a truncated `ENCRYPTION_KEY` or signing key would be
    printed by the very error that refuses it. In CI the key is generated and disposable, but
    the deployed `backend`/`worker`/`beat`/`migrate` containers receive the real
    Terraform-provisioned one, and an invalid value there would land in container logs.

    R3.4 requires failing "nombrando la variable y sin imprimir su valor", which is exactly
    the pair `errors(include_input=False)` gives: the field path and the reason, no value.
    """


def _load_settings() -> "Settings":
    problems: str | None = None
    try:
        return Settings()
    except ValidationError as error:
        problems = "; ".join(
            # `loc` is the field path, `msg` the reason. `include_input=False` is the whole
            # point of this function — with it left on, this wrapper would leak exactly what
            # it exists to withhold. Note `loc` is EMPTY for a model-level validator, so the
            # field name reaches the reader through `msg`, which names it.
            f"{'.'.join(str(part) for part in item['loc']) or '(model)'}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )

    # Raised OUTSIDE the except block, and that placement is load-bearing. `raise ... from None`
    # is not enough: it only sets `__suppress_context__`, while `__context__` keeps pointing at
    # the original `ValidationError` — which still carries the whole submitted input. The
    # default traceback printer honours the suppression flag, but anything that walks the
    # exception chain (a log formatter, an error reporter) reads straight through it.
    #
    # Measured on this branch: that chained input contained the invalid key AND a
    # `bootstrap_*_password`, so this is wider than the key it was written for. Outside the
    # except block the exception is no longer being handled, so `__context__` is never set.
    raise ConfigurationError(f"invalid configuration: {problems}")


settings = _load_settings()
