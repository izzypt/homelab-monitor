"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "production"
    log_level: str = "INFO"
    timezone: str = "Europe/Lisbon"

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "homelab_monitor"
    postgres_user: str = "homelab_monitor"
    postgres_password: str = Field(default="", repr=False)

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = Field(default="", repr=False)

    # healthchecks.io ping URL for the "homelab-monitor" check (pinged by beat). Empty = disabled.
    healthcheck_ping_url: str = Field(default="", repr=False)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def redis_url(self, db: int = 0) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
