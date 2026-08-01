from pathlib import Path

from pydantic import Field, model_validator
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

    # Limits of the CSV reservation import (R4.3, design D11). Both are checked BEFORE
    # parsing: a 200 MB upload must be refused, not streamed into memory first. The byte
    # ceiling is rule 6 of `steering/security.md` ("tamaño máx. configurable, default 10 MB");
    # the row ceiling is this change's, because a small file can still hold a million rows.
    csv_import_max_bytes: int = 10 * 1024 * 1024
    csv_import_max_rows: int = 1000

    bootstrap_tenant_name: str = ""
    bootstrap_tenant_billing_email: str = ""
    bootstrap_owner_name: str = ""
    bootstrap_owner_email: str = ""
    bootstrap_owner_password: str = ""
    bootstrap_manager_name: str = ""
    bootstrap_manager_email: str = ""
    bootstrap_manager_password: str = ""

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
