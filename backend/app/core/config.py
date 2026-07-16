from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT_ENV_FILE, extra="ignore")

    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    redis_url: str = "redis://redis:6379/0"
    database_url: str = ""

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
