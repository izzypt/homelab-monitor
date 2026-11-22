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

    # Sessions and login (README section 10).
    session_cookie_name: str = "hm_session"
    session_cookie_secure: bool = True  # set False only for local http development
    session_idle_s: int = 24 * 3600
    session_absolute_s: int = 7 * 24 * 3600
    login_attempts_per_minute: int = 5

    # Monitor checks.
    check_user_agent: str = "homelab-monitor/0.1"
    tls_warning_days: int = 14

    # Email alerts. Empty smtp_host = alerts are recorded but marked failed (not configured).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_starttls: bool = True
    alert_from: str = ""
    alert_recipients: str = ""  # comma-separated; lives only in .env

    @property
    def alert_recipient_list(self) -> list[str]:
        return [a.strip() for a in self.alert_recipients.split(",") if a.strip()]

    # Containers: the Docker API through the read-only socket proxy, recorded under this host.
    docker_api_url: str = "http://docker-proxy:2375"
    docker_host_name: str = "mac-mini"

    # Local network outage detection: if every control target fails twice in a row, monitor
    # DOWN emails are replaced by a single "network outage" email.
    network_control_urls: str = "https://1.1.1.1,https://www.google.com"

    @property
    def network_control_url_list(self) -> list[str]:
        return [u.strip() for u in self.network_control_urls.split(",") if u.strip()]

    # Retention (README section 6). Nothing is kept forever.
    raw_retention_days: int = 30
    summary_retention_days: int = 183

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
