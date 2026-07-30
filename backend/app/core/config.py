from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# Deliberately NOT configurable (design D3): a deployment that set this to "none"
# would disable signature verification altogether.
JWT_ALGORITHM = "HS256"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT_ENV_FILE, extra="ignore")

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

    # Name of the header carrying the real client IP, honoured only when set
    # (design D12). Empty means "trust nothing but the socket peer": no proxy
    # currently fronts the API, so an X-Forwarded-For would be caller-supplied.
    trusted_client_ip_header: str = ""

    # Build identity, baked into the image by the CD as ENV (change
    # app-version-visibility, design D4). Every field has a default ON PURPOSE — the
    # opposite of jwt_secret_key, which is required so the app refuses to boot without
    # it. `settings = Settings()` runs at import time, so a required field here would
    # turn an image built without build-args (a local `docker compose build`, a
    # hand-built one) into a ValidationError before the app can serve a single request.
    # Knowing which version is deployed must never be able to prevent deploying.
    app_version: str = ""
    build_commit: str = ""
    build_pr: int | None = None
    built_at: str = ""
    build_run_id: str = ""
    build_ref: str = ""

    bootstrap_tenant_name: str = ""
    bootstrap_tenant_billing_email: str = ""
    bootstrap_owner_name: str = ""
    bootstrap_owner_email: str = ""
    bootstrap_owner_password: str = ""
    bootstrap_manager_name: str = ""
    bootstrap_manager_email: str = ""
    bootstrap_manager_password: str = ""

    @field_validator("build_pr", mode="before")
    @classmethod
    def _unparseable_build_pr_is_none(cls, value: object) -> object:
        """Anything that is not a plain positive integer becomes None, never an error.

        The coercion is TOTAL on purpose. `settings = Settings()` runs at import time, so
        a ValidationError on this field means the image does not boot at all — the exact
        failure R2.10 forbids ("la versión nunca debe poder impedir el arranque"), and
        losing the whole deployment is a far worse outcome than losing one metadata field.

        The value is composed outside this module (the `#(\\d+)` extraction lives in
        deploy-dev.yml, design D3) and the Dockerfile always defines `ENV BUILD_PR`, so
        every unexpected shape has to degrade rather than kill: an empty string (a direct
        push to main with no PR, R1.7), a literal "unknown" — one of the two renderings
        R2.6 sanctions — or anything malformed like "#42" or "42a".
        """
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None

    @model_validator(mode="after")
    def _reject_whitespace_jwt_secret(self) -> "Settings":
        if len(self.jwt_secret_key.strip()) < 32:
            raise ValueError(
                "jwt_secret_key must have at least 32 non-whitespace characters"
            )
        return self

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


settings = Settings()
